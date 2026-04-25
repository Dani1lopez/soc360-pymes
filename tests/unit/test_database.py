"""Tests for app/core/database.py — set_tenant_context parameterized SQL."""
from __future__ import annotations

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock

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
