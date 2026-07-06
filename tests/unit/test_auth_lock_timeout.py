"""Tests for issue #138: advisory lock timeout prevents indefinite blocking.

Verifies that _acquire_session_cap_lock:
1. Sets lock_timeout before acquiring the advisory lock.
2. Converts lock timeout errors (SQLSTATE 55P03) into ServiceUnavailableError.
3. Does not hang indefinitely under contention.
4. Re-raises non-lock DBAPIErrors (and OperationalErrors) unchanged.
5. Detects lock timeouts robustly across dialect wrappers.
6. Handles generic DBAPIError wrappers (asyncpg maps LockNotAvailableError
   through DBAPIError, not OperationalError).
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.exceptions import ServiceUnavailableError
from app.modules.auth.service import (
    _ADVISORY_LOCK_SQL,
    _ADVISORY_LOCK_TIMEOUT_MS,
    _LOCK_TIMEOUT_SQL,
    _acquire_session_cap_lock,
    _is_lock_timeout_error,
)

_USER_ID = UUID("12345678-1234-1234-1234-123456789abc")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(
    execute_side_effect=None,
    in_transaction: bool = True,
) -> MagicMock:
    """Build a mock AsyncSession with a *synchronous* in_transaction().

    AsyncSession.in_transaction() is a regular sync method returning bool.
    Using AsyncMock for it causes RuntimeWarning (unawaited coroutine).
    We use MagicMock for the container and explicitly set in_transaction as
    a sync callable, while execute is an AsyncMock (or custom async func).
    """
    mock_db = MagicMock()
    # in_transaction is SYNC on AsyncSession — must NOT be an AsyncMock.
    mock_db.in_transaction = MagicMock(return_value=in_transaction)
    if execute_side_effect is not None:
        mock_db.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        mock_db.execute = AsyncMock()
    return mock_db


class _FakeLockNotAvailableError(Exception):
    """Stand-in for asyncpg.LockNotAvailableError in unit tests."""

    pass


def _make_op_error(orig: Exception) -> OperationalError:
    return OperationalError(
        statement="SELECT pg_advisory_xact_lock(...)",
        params={},
        orig=orig,
    )


def _make_dbapi_error(orig: Exception) -> DBAPIError:
    """Build a plain DBAPIError (not OperationalError) wrapping *orig*.

    This simulates the asyncpg path where LockNotAvailableError is mapped
    through the generic DBAPI Error, which SQLAlchemy wraps as DBAPIError
    rather than OperationalError.
    """
    return DBAPIError(
        statement="SELECT pg_advisory_xact_lock(...)",
        params={},
        orig=orig,
    )


# ---------------------------------------------------------------------------
# Ordering & structural tests
# ---------------------------------------------------------------------------


class TestAcquireSessionCapLockOrdering:
    """Issue #138: SET LOCAL lock_timeout must precede the advisory lock."""

    @pytest.mark.asyncio
    async def test_sets_lock_timeout_before_advisory_lock(self):
        """_acquire_session_cap_lock must call SET LOCAL lock_timeout first."""
        execute_calls: list[tuple[str, dict | None]] = []

        async def track_execute(stmt, params=None):
            execute_calls.append((str(stmt).lower(), params))

        mock_db = MagicMock()
        mock_db.in_transaction = MagicMock(return_value=True)
        mock_db.execute = track_execute

        await _acquire_session_cap_lock(_USER_ID, mock_db)

        assert len(execute_calls) == 2

        # First call must be the lock_timeout SET with transaction-local flag.
        first_stmt, first_params = execute_calls[0]
        assert "set_config" in first_stmt
        assert "lock_timeout" in first_stmt
        # The SQL must pass is_local=true so the timeout is transaction-scoped.
        assert "true" in first_stmt
        assert first_params == {"timeout_ms": _ADVISORY_LOCK_TIMEOUT_MS}

        # Second call must be the advisory lock.
        second_stmt, _ = execute_calls[1]
        assert "pg_advisory_xact_lock" in second_stmt

    @pytest.mark.asyncio
    async def test_lock_timeout_sql_is_transaction_local(self):
        """Structural check: lock_timeout SQL uses set_config with is_local=true."""
        sql_str = str(_LOCK_TIMEOUT_SQL).lower()
        assert "set_config" in sql_str
        assert "lock_timeout" in sql_str
        # The third argument to set_config must be 'true' for LOCAL scope.
        assert "true" in sql_str

    @pytest.mark.asyncio
    async def test_still_requires_active_transaction(self):
        """_acquire_session_cap_lock raises RuntimeError without active tx."""
        mock_db = _make_db(in_transaction=False)

        with pytest.raises(RuntimeError, match="requires an active transaction"):
            await _acquire_session_cap_lock(_USER_ID, mock_db)

        # execute must NOT have been called — the guard fires first.
        mock_db.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Error conversion tests
# ---------------------------------------------------------------------------


class TestLockTimeoutErrorConversion:
    """LockNotAvailableError (55P03) -> ServiceUnavailableError."""

    @pytest.mark.asyncio
    async def test_lock_timeout_raises_service_unavailable(self):
        """asyncpg-style LockNotAvailableError -> ServiceUnavailableError."""
        fake_orig = _FakeLockNotAvailableError(
            "canceling statement due to lock timeout"
        )
        op_error = _make_op_error(fake_orig)

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return  # lock_timeout SET succeeds
            raise op_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch("asyncpg.LockNotAvailableError", _FakeLockNotAvailableError):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await _acquire_session_cap_lock(_USER_ID, mock_db)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_does_not_hang_raises_promptly(self):
        """Lock contention must raise ServiceUnavailableError promptly, not hang."""
        fake_orig = _FakeLockNotAvailableError("lock timeout")
        op_error = _make_op_error(fake_orig)

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            await asyncio.sleep(0.05)
            raise op_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch("asyncpg.LockNotAvailableError", _FakeLockNotAvailableError):
            with pytest.raises(ServiceUnavailableError):
                await asyncio.wait_for(
                    _acquire_session_cap_lock(_USER_ID, mock_db),
                    timeout=5.0,
                )

    @pytest.mark.asyncio
    async def test_non_lock_operational_error_reraises(self):
        """Non-lock OperationalError must propagate unchanged."""

        class FakeConnectionError(Exception):
            pass

        op_error = _make_op_error(FakeConnectionError("connection lost"))

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise op_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch("asyncpg.LockNotAvailableError", _FakeLockNotAvailableError):
            with pytest.raises(OperationalError):
                await _acquire_session_cap_lock(_USER_ID, mock_db)

    @pytest.mark.asyncio
    async def test_generic_dbapi_error_with_55p03_converts(self):
        """Generic DBAPIError (not OperationalError) wrapping 55P03 -> 503.

        asyncpg maps LockNotAvailableError through the generic DBAPI Error,
        which SQLAlchemy wraps as DBAPIError rather than OperationalError.
        This must still be converted to ServiceUnavailableError.
        """

        class FakeOrigWithSqlstate(Exception):
            sqlstate = "55P03"

        dbapi_error = _make_dbapi_error(FakeOrigWithSqlstate("lock timeout"))

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise dbapi_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch.dict("sys.modules", {"asyncpg": None}):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await _acquire_session_cap_lock(_USER_ID, mock_db)

        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_non_lock_dbapi_error_reraises(self):
        """Non-lock DBAPIError must propagate unchanged (not converted)."""

        class FakeConnectionError(Exception):
            pass

        dbapi_error = _make_dbapi_error(FakeConnectionError("connection lost"))

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise dbapi_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with pytest.raises(DBAPIError):
            await _acquire_session_cap_lock(_USER_ID, mock_db)


# ---------------------------------------------------------------------------
# Robust detection tests (unit-level, no PG required)
# ---------------------------------------------------------------------------


class TestIsLockTimeoutErrorDetection:
    """_is_lock_timeout_error must detect 55P03 across dialect wrappers."""

    def test_asyncpg_isinstance_match(self):
        """asyncpg.LockNotAvailableError is detected via isinstance."""
        orig = _FakeLockNotAvailableError("lock timeout")
        exc = _make_op_error(orig)
        with patch("asyncpg.LockNotAvailableError", _FakeLockNotAvailableError):
            assert _is_lock_timeout_error(exc) is True

    def test_sqlstate_attribute_on_orig(self):
        """orig.sqlstate == '55P03' is detected (asyncpg dialect attribute)."""

        class FakeOrig(Exception):
            sqlstate = "55P03"

        exc = _make_op_error(FakeOrig("lock timeout"))
        # Force asyncpg import to "fail" so we exercise the attribute path.
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is True

    def test_pgcode_attribute_on_orig(self):
        """orig.pgcode == '55P03' is detected (psycopg2 dialect attribute)."""

        class FakeOrig(Exception):
            pgcode = "55P03"

        exc = _make_op_error(FakeOrig("lock timeout"))
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is True

    def test_code_attribute_on_orig(self):
        """orig.code == '55P03' is detected (generic dialect attribute)."""

        class FakeOrig(Exception):
            code = "55P03"

        exc = _make_op_error(FakeOrig("lock timeout"))
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is True

    def test_string_fallback_55p03(self):
        """String representation containing '55P03' is detected as fallback."""
        fake_orig = Exception("ERROR: 55P03 lock_not_available")
        exc = _make_op_error(fake_orig)
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is True

    def test_string_fallback_case_insensitive_not_required(self):
        """SQLSTATE is uppercase; we match the exact code."""
        fake_orig = Exception("ERROR: 55p03 lowercase")
        exc = _make_op_error(fake_orig)
        with patch.dict("sys.modules", {"asyncpg": None}):
            # Our detection is case-sensitive for the standard SQLSTATE code.
            assert _is_lock_timeout_error(exc) is False

    def test_unrelated_operational_error_not_matched(self):
        """Non-lock OperationalError is NOT detected as lock timeout."""
        fake_orig = Exception("connection refused")
        exc = _make_op_error(fake_orig)
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is False

    def test_none_orig_not_matched(self):
        """OperationalError with orig=None is not a lock timeout."""
        exc = OperationalError(statement="stmt", params={}, orig=None)
        assert _is_lock_timeout_error(exc) is False

    def test_wrong_sqlstate_not_matched(self):
        """A different SQLSTATE (e.g. 40001 serialization failure) is not matched."""

        class FakeOrig(Exception):
            sqlstate = "40001"

        exc = _make_op_error(FakeOrig("serialization failure"))
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is False

    def test_dbapi_error_with_55p03_detected(self):
        """Generic DBAPIError (not OperationalError) with 55P03 is detected."""

        class FakeOrig(Exception):
            sqlstate = "55P03"

        exc = _make_dbapi_error(FakeOrig("lock timeout"))
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is True

    def test_dbapi_error_non_lock_not_matched(self):
        """Generic DBAPIError without 55P03 is NOT detected as lock timeout."""
        fake_orig = Exception("connection refused")
        exc = _make_dbapi_error(fake_orig)
        with patch.dict("sys.modules", {"asyncpg": None}):
            assert _is_lock_timeout_error(exc) is False


# ---------------------------------------------------------------------------
# Fallback path integration (asyncpg unavailable)
# ---------------------------------------------------------------------------


class TestFallbackDetection:
    """Test the fallback detection path when asyncpg is not importable."""

    @pytest.mark.asyncio
    async def test_fallback_detects_55p03_in_error_string(self):
        """When asyncpg import fails, detect lock timeout via SQLSTATE 55P03."""
        fake_orig = Exception("ERROR: 55P03 lock_not_available")
        op_error = _make_op_error(fake_orig)

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise op_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch.dict("sys.modules", {"asyncpg": None}):
            with pytest.raises(ServiceUnavailableError):
                await _acquire_session_cap_lock(_USER_ID, mock_db)

    @pytest.mark.asyncio
    async def test_fallback_detects_sqlstate_attribute(self):
        """When asyncpg import fails, detect via orig.sqlstate attribute."""

        class FakeOrig(Exception):
            sqlstate = "55P03"

        op_error = _make_op_error(FakeOrig("lock timeout"))

        call_count = 0

        async def execute_side_effect(stmt, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return
            raise op_error

        mock_db = _make_db(execute_side_effect=execute_side_effect)

        with patch.dict("sys.modules", {"asyncpg": None}):
            with pytest.raises(ServiceUnavailableError):
                await _acquire_session_cap_lock(_USER_ID, mock_db)


# ---------------------------------------------------------------------------
# Optional: real PostgreSQL integration test (skipped if PG unavailable)
# ---------------------------------------------------------------------------

_PG_DSN = os.environ.get("TEST_PG_DSN")


@pytest.mark.skipif(not _PG_DSN, reason="TEST_PG_DSN not set — skip PG integration")
class TestPGIntegrationLockTimeout:
    """Real PostgreSQL integration: prove lock_timeout fires and is converted.

    Requires a running PostgreSQL instance accessible via TEST_PG_DSN.
    These tests are skipped in CI unless the env var is set.
    """

    @pytest.mark.asyncio
    async def test_real_lock_timeout_converts_to_service_unavailable(self):
        """With a real PG, a contended advisory lock triggers 55P03 -> 503."""
        from sqlalchemy import text as sa_text
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        engine = create_async_engine(_PG_DSN)
        try:
            async with engine.begin() as conn:
                # Set a very short lock_timeout so the test is fast.
                await conn.execute(
                    sa_text("SELECT set_config('lock_timeout', '50', true)")
                )
                # Acquire the lock in this transaction.
                await conn.execute(
                    sa_text(
                        "SELECT pg_advisory_xact_lock("
                        "hashtextextended('test-user', 0))"
                    )
                )

                # Now open a second session that will contend for the same lock.
                async with engine.begin() as conn2:
                    await conn2.execute(
                        sa_text("SELECT set_config('lock_timeout', '50', true)")
                    )
                    with pytest.raises(OperationalError) as exc_info:
                        await conn2.execute(
                            sa_text(
                                "SELECT pg_advisory_xact_lock("
                                "hashtextextended('test-user', 0))"
                            )
                        )
                    # Verify the error is detected as a lock timeout.
                    assert _is_lock_timeout_error(exc_info.value)
        finally:
            await engine.dispose()
