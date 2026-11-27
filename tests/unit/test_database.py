"""Tests for app/core/database.py — set_tenant_context parameterized SQL."""
from __future__ import annotations

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

import pytest


class TestSetTenantContextParameterized:
    """Verify set_tenant_context uses bind parameters, not SQL interpolation."""

    @pytest.mark.asyncio
    async def test_tenant_branch_no_sql_interpolation(self):
        """set_tenant_context MUST NOT interpolate tenant_id into the SQL string."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        tenant_id = uuid4()

        await set_tenant_context(mock_db, tenant_id, is_superadmin=False)

        # Primer call: set_config para current_tenant
        call_sql = mock_db.execute.call_args_list[0]
        sql_text = call_call_sql(call_sql)

        # El SQL NO debe contener el tenant_id como literal entrecomillado
        assert str(tenant_id) not in sql_text, (
            f"SQL string contains interpolated tenant_id: {sql_text}"
        )
        # El SQL debe usar el placeholder :tenant_id
        assert ":tenant_id" in sql_text, (
            f"SQL string does not use bind parameter :tenant_id: {sql_text}"
        )
        # Los parámetros deben incluir tenant_id
        assert call_call_params(call_sql) == {"tenant_id": str(tenant_id)}

    @pytest.mark.asyncio
    async def test_tenant_branch_sets_superadmin_false(self):
        """set_tenant_context tenant branch MUST set is_superadmin to 'false'."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        await set_tenant_context(mock_db, uuid4(), is_superadmin=False)

        # Segundo call: set_config para is_superadmin = 'false'
        call_sql = mock_db.execute.call_args_list[1]
        sql_text = call_call_sql(call_sql)

        assert "is_superadmin" in sql_text
        assert "'false'" in sql_text
        assert ":tenant_id" not in sql_text
        assert call_call_params(call_sql) is None or call_call_params(call_sql) == {}

    @pytest.mark.asyncio
    async def test_superadmin_branch_no_sql_interpolation(self):
        """set_tenant_context superadmin branch MUST NOT interpolate anything."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock()
        mock_db.execute = AsyncMock()

        await set_tenant_context(mock_db, None, is_superadmin=True)

        call_sql = mock_db.execute.call_args_list[0]
        sql_text = call_call_sql(call_sql)

        assert "is_superadmin" in sql_text
        assert "'true'" in sql_text
        assert ":tenant_id" not in sql_text
        assert str(uuid4()) not in sql_text
        assert call_call_params(call_sql) is None or call_call_params(call_sql) == {}

    @pytest.mark.asyncio
    async def test_raises_value_error_without_tenant_and_not_superadmin(self):
        """set_tenant_context MUST raise ValueError when tenant_id is None and is_superadmin is False."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock()

        with pytest.raises(ValueError, match="tenant_id requerido"):
            await set_tenant_context(mock_db, None, is_superadmin=False)


class TestSetTenantContextSuperadminCombinedSQL:
    """Verify set_tenant_context superadmin branch uses a SINGLE combined roundtrip.

    This guards against session poisoning across pooled connections: a superadmin
    query that follows a regular tenant query on the same connection would be
    silently filtered by the previous tenant's RLS policy unless we explicitly
    clear `app.current_tenant` in the SAME roundtrip that elevates privileges.
    """

    @pytest.mark.asyncio
    async def test_set_tenant_context_superadmin_clears_tenant(self):
        """When is_superadmin=True, set_tenant_context must also clear
        app.current_tenant to prevent RLS session poisoning across
        pooled connections."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()
        mock_db.execute.return_value = MagicMock()

        await set_tenant_context(db=mock_db, tenant_id="abc-123", is_superadmin=True)

        # Single roundtrip — both set_config calls combined into one query
        assert mock_db.execute.call_count == 1, (
            f"Expected 1 roundtrip combining both set_config calls, "
            f"got {mock_db.execute.call_count}"
        )

        # The combined SQL must set BOTH is_superadmin=true AND current_tenant=''
        sql = str(mock_db.execute.call_args_list[0][0][0])
        assert "app.is_superadmin" in sql
        assert "'true'" in sql
        assert "app.current_tenant" in sql
        assert "''" in sql

    @pytest.mark.asyncio
    async def test_set_tenant_context_regular_user_sets_tenant(self):
        """When is_superadmin=False, set_tenant_context sets the tenant_id
        via bind parameter and sets is_superadmin to 'false' in a second
        roundtrip. Regular users MUST NOT get is_superadmin='true'."""
        from app.core.database import set_tenant_context

        mock_db = MagicMock(spec=AsyncSession)
        mock_db.execute = AsyncMock()

        await set_tenant_context(
            db=mock_db, tenant_id="tenant-xyz", is_superadmin=False
        )

        # Two roundtrips: one for current_tenant (bind param), one for is_superadmin='false'
        assert mock_db.execute.call_count == 2

        # First call sets current_tenant via bind parameter (NO string interpolation)
        first_sql = str(mock_db.execute.call_args_list[0][0][0])
        assert "app.current_tenant" in first_sql
        assert ":tenant_id" in first_sql
        # The literal tenant value must NOT be interpolated
        assert "tenant-xyz" not in first_sql
        # But the bind params must include it
        first_params = mock_db.execute.call_args_list[0][0][1]
        assert first_params == {"tenant_id": "tenant-xyz"}

        # Second call sets is_superadmin to 'false' (NOT 'true')
        second_sql = str(mock_db.execute.call_args_list[1][0][0])
        assert "app.is_superadmin" in second_sql
        assert "'false'" in second_sql
        assert "'true'" not in second_sql


def call_call_sql(call_args) -> str:
    """Extract SQL string from mock.call_args."""
    # call_args: tuple((args, kwargs)) — positional args[0] = SQL text object
    return call_args[0][0].text if hasattr(call_args[0][0], "text") else str(call_args[0][0])


def call_call_params(call_args) -> dict | None:
    """Extract params dict from mock.call_args."""
    if call_args[0].__len__() > 1:
        return call_args[0][1]
    if "params" in call_args[1]:
        return call_args[1]["params"]
    return None


class TestBuildConnectArgs:
    """Verify _build_connect_args produces correct asyncpg server_settings
    (issue #134).

    The helper is a pure function — no module reload or SQLAlchemy monkeypatch
    needed. This avoids polluting app.core.database.engine / AsyncSessionLocal
    with mock-derived globals.
    """

    def test_returns_statement_and_lock_timeout_as_strings(self):
        """_build_connect_args MUST return server_settings with string values
        for statement_timeout and lock_timeout."""
        from app.core.database import _build_connect_args

        result = _build_connect_args(12345, 6789)

        assert result == {
            "server_settings": {
                "statement_timeout": "12345",
                "lock_timeout": "6789",
            },
        }

    def test_default_timeout_values(self):
        """The module-level engine MUST be created with default timeout values
        when no env override is set (30s statement, 5s lock)."""
        from app.core.config import settings

        assert settings.DB_STATEMENT_TIMEOUT_MS == 30_000
        assert settings.DB_LOCK_TIMEOUT_MS == 5_000


def _fake_session_cm(session: AsyncMock) -> MagicMock:
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestGetDbLifecycle:
    @pytest.mark.asyncio
    async def test_commits_when_transaction_is_still_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import database
        from app.core.database import get_db

        session = AsyncMock()
        session.in_transaction = MagicMock(return_value=True)
        monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _fake_session_cm(session))

        gen = get_db()
        yielded = await gen.__anext__()
        assert yielded is session

        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        session.commit.assert_awaited_once()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_commit_after_in_service_commit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import database
        from app.core.database import get_db

        session = AsyncMock()
        session.in_transaction = MagicMock(return_value=False)
        monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _fake_session_cm(session))

        gen = get_db()
        await gen.__anext__()
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()

        session.commit.assert_not_awaited()
        session.rollback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rolls_back_on_exception_when_in_transaction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.core import database
        from app.core.database import get_db

        session = AsyncMock()
        session.in_transaction = MagicMock(return_value=True)
        monkeypatch.setattr(database, "AsyncSessionLocal", lambda: _fake_session_cm(session))

        gen = get_db()
        await gen.__anext__()
        with pytest.raises(RuntimeError, match="boom"):
            await gen.athrow(RuntimeError("boom"))

        session.rollback.assert_awaited_once()
        session.commit.assert_not_awaited()


class TestTenantContextReapply:
    @pytest.mark.asyncio
    async def test_set_tenant_context_stores_canonical_context_and_uses_is_local(self) -> None:
        from app.core.database import _TENANT_CONTEXT_KEY, set_tenant_context

        db = AsyncMock()
        db.info = {}
        tenant_id = UUID("11111111-1111-1111-1111-111111111111")

        await set_tenant_context(db, tenant_id=tenant_id, is_superadmin=False)

        assert db.info[_TENANT_CONTEXT_KEY] == (tenant_id, False)
        assert db.execute.await_count == 2
        first_stmt, first_params = db.execute.await_args_list[0].args
        second_stmt, second_params = db.execute.await_args_list[1].args
        assert "set_config('app.current_tenant', :tenant_id, true)" in str(first_stmt)
        assert first_params == {"tenant_id": str(tenant_id)}
        assert "set_config('app.is_superadmin', 'false', true)" in str(second_stmt)
        assert second_params == {}

    def test_after_begin_reapplies_set_config_only_on_non_nested_with_context(self) -> None:
        from types import SimpleNamespace

        from app.core.database import _TENANT_CONTEXT_KEY, _reapply_tenant_context_on_begin

        conn = MagicMock()
        session = SimpleNamespace(info={})
        tx = SimpleNamespace(nested=False)

        _reapply_tenant_context_on_begin(session, tx, conn)
        conn.execute.assert_not_called()

        tenant_id = UUID("22222222-2222-2222-2222-222222222222")
        session.info[_TENANT_CONTEXT_KEY] = (tenant_id, False)

        _reapply_tenant_context_on_begin(session, SimpleNamespace(nested=True), conn)
        conn.execute.assert_not_called()

        _reapply_tenant_context_on_begin(session, tx, conn)
        assert conn.execute.call_count == 2
        first_stmt, first_params = conn.execute.call_args_list[0].args
        second_stmt, second_params = conn.execute.call_args_list[1].args
        assert "set_config('app.current_tenant', :tenant_id, true)" in str(first_stmt)
        assert first_params == {"tenant_id": str(tenant_id)}
        assert "set_config('app.is_superadmin', 'false', true)" in str(second_stmt)
        assert second_params == {}

    def test_sqlalchemy_event_fires_on_real_session_begin_after_commit(self) -> None:
        from sqlalchemy import create_engine, event, text
        from sqlalchemy.orm import Session

        engine = create_engine("sqlite:///:memory:")
        captured_set_config: list[tuple[str, object]] = []
        tenant_id = UUID("33333333-3333-3333-3333-333333333333")

        @event.listens_for(engine, "before_cursor_execute", retval=True)
        def _intercept_set_config(_conn, _cursor, statement, parameters, _ctx, _many):
            if "set_config" in statement:
                captured_set_config.append((statement, parameters))
                return "SELECT 1", ()
            return statement, parameters

        from app.core.database import _TENANT_CONTEXT_KEY

        with Session(engine) as session:
            session.execute(text("SELECT 1"))
            assert captured_set_config == []

            session.info[_TENANT_CONTEXT_KEY] = (tenant_id, False)
            session.commit()

            session.execute(text("SELECT 1"))

        assert len(captured_set_config) == 2
        sql_tenant, params_tenant = captured_set_config[0]
        sql_admin, params_admin = captured_set_config[1]
        assert "set_config('app.current_tenant'" in sql_tenant
        assert params_tenant == (str(tenant_id),)
        assert "set_config('app.is_superadmin', 'false', true)" in sql_admin
        assert params_admin == ()
        engine.dispose()
