"""Tests for app/dependencies.py — T3.1: EventBus dependency injection."""
from __future__ import annotations

from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fakeredis.aioredis import FakeRedis


class TestGetCurrentUserTenantContext:
    """#40 — get_current_user MUST set RLS tenant context after validation."""

    @pytest.fixture
    def valid_token_payload(self):
        return {"sub": str(uuid4()), "jti": "jti-123"}

    @pytest.fixture
    def mock_db_and_row(self):
        mock_user = MagicMock()
        mock_user.is_active = True
        mock_user.is_superadmin = False
        mock_user.tenant_id = uuid4()
        mock_user.id = uuid4()

        mock_tenant = MagicMock()
        mock_tenant.is_active = True

        mock_row = MagicMock()
        mock_row.User = mock_user
        mock_row.Tenant = mock_tenant

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        return mock_db, mock_user, mock_tenant

    @pytest.mark.asyncio
    async def test_superadmin_sets_tenant_context_with_is_superadmin_true(
        self, valid_token_payload, mock_db_and_row
    ):
        """T2: Superadmin → set_tenant_context called with is_superadmin=True."""
        mock_db, mock_user, _ = mock_db_and_row
        mock_user.is_superadmin = True
        mock_user.tenant_id = uuid4()

        with patch("app.dependencies.auth.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.auth.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.auth.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.auth.set_tenant_context", AsyncMock()) as mock_set_ctx:
            from app.dependencies import get_current_user
            result = await get_current_user(
                token="Bearer token",
                db=mock_db,
                redis=AsyncMock(),
            )

        mock_set_ctx.assert_awaited_once_with(
            mock_db, mock_user.tenant_id, True
        )
        assert result is mock_user

    @pytest.mark.asyncio
    async def test_normal_user_sets_tenant_context_with_tenant_id(
        self, valid_token_payload, mock_db_and_row
    ):
        """T3: Normal user → set_tenant_context called with correct tenant_id."""
        mock_db, mock_user, _ = mock_db_and_row
        mock_user.is_superadmin = False
        mock_user.tenant_id = uuid4()

        with patch("app.dependencies.auth.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.auth.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.auth.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.auth.set_tenant_context", AsyncMock()) as mock_set_ctx:
            from app.dependencies import get_current_user
            result = await get_current_user(
                token="Bearer token",
                db=mock_db,
                redis=AsyncMock(),
            )

        mock_set_ctx.assert_awaited_once_with(
            mock_db, mock_user.tenant_id, False
        )
        assert result is mock_user

    @pytest.mark.asyncio
    async def test_non_superadmin_without_tenant_id_returns_401(
        self, valid_token_payload, mock_db_and_row
    ):
        """T4: Non-superadmin with tenant_id=None → 401, no set_tenant_context call."""
        mock_db, mock_user, _ = mock_db_and_row
        mock_user.is_superadmin = False
        mock_user.tenant_id = None

        with patch("app.dependencies.auth.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.auth.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.auth.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.auth.set_tenant_context", AsyncMock()) as mock_set_ctx:
            from app.dependencies import get_current_user
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    token="Bearer token",
                    db=mock_db,
                    redis=AsyncMock(),
                )

        assert exc_info.value.status_code == 401
        mock_set_ctx.assert_not_awaited()


class TestGetEventBus:
    """Validate get_event_bus() dependency."""

    @pytest.mark.asyncio
    async def test_get_event_bus_returns_event_bus_instance(self):
        """get_event_bus() MUST return an EventBus instance with a redis client."""
        # Patch get_redis_client so we don't need real Redis
        mock_redis = FakeRedis()
        with patch("app.dependencies.event_deps.get_redis_client", AsyncMock(return_value=mock_redis)):
            # Import inside to allow patching first
            from app.dependencies import get_event_bus

            result = await get_event_bus()
            from app.event_bus import EventBus

            assert isinstance(result, EventBus)
            assert result._redis is mock_redis
        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_get_event_bus_returns_singleton(self):
        """get_event_bus() MUST return the SAME instance on repeated calls."""
        mock_redis = FakeRedis()
        with patch("app.dependencies.event_deps.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instance1 = await get_event_bus()
            instance2 = await get_event_bus()
            assert instance1 is instance2
        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_get_event_bus_singleton_across_multiple_calls(self):
        """get_event_bus() singleton MUST hold across >2 calls."""
        mock_redis = FakeRedis()
        with patch("app.dependencies.event_deps.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instances = [await get_event_bus() for _ in range(5)]
            assert all(inst is instances[0] for inst in instances)
        await mock_redis.aclose()


# ---------------------------------------------------------------------------
# PR-A: cross-tenant pre-check Depends (T-PRA.01, T-PRA.02, T-PRA.04, T-PRA.11,
# T-PRA.12, T-PRA.13)
# ---------------------------------------------------------------------------


class TestLogCrossTenantAttempt:
    """T-PRA.13 — _log_cross_tenant_attempt emits a single chokepoint log line."""

    def test_log_cross_tenant_attempt_includes_required_fields(self):
        """T-PRA.13: log MUST contain caller_id, target_id, method, endpoint
        and MUST NOT contain tenant_id (OQ-1 sensitive info avoidance).
        """
        from app.dependencies import _log_cross_tenant_attempt

        caller_id = uuid4()
        target_id = uuid4()

        with patch("app.dependencies.cross_tenant.logger") as mock_logger:
            _log_cross_tenant_attempt(
                caller_id=caller_id,
                target_id=target_id,
                method="GET",
                endpoint=f"/users/{target_id}",
            )

        mock_logger.warning.assert_called_once()
        call_args, call_kwargs = mock_logger.warning.call_args
        # The event name is the first positional arg.
        assert call_args == ("cross_tenant_access_blocked",)
        assert call_kwargs["caller_id"] == str(caller_id)
        assert call_kwargs["target_id"] == str(target_id)
        assert call_kwargs["method"] == "GET"
        assert call_kwargs["endpoint"] == f"/users/{target_id}"
        # NO tenant_id field.
        assert "tenant_id" not in call_kwargs


class TestGetUserForAdmin:
    """T-PRA.11 — _get_user_for_admin covers same-tenant, cross-tenant 403,
    superadmin bypass, and missing-row 404."""

    @pytest.fixture
    def user_id(self):
        return uuid4()

    @pytest.fixture
    def same_tenant_id(self):
        return uuid4()

    @pytest.fixture
    def other_tenant_id(self):
        return uuid4()

    @pytest.mark.asyncio
    async def test_get_user_for_admin_returns_row_on_match(
        self, user_id, same_tenant_id
    ):
        """Same-tenant caller gets the row, no superadmin elevation needed."""
        from app.dependencies import _get_user_for_admin

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.tenant_id = same_tenant_id

        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.tenant_id = same_tenant_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        # set_tenant_context is awaited in the finally block.
        with patch("app.dependencies.cross_tenant.set_tenant_context", AsyncMock()) as mock_set_ctx:
            mock_db.execute.return_value = mock_result
            row = await _get_user_for_admin(
                user_id, mock_caller, mock_db, method="GET", endpoint=f"/users/{user_id}"
            )

        assert row is mock_user
        # Same-tenant: no elevation, restore context was still called.
        mock_set_ctx.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_user_for_admin_raises_403_on_tenant_mismatch(
        self, user_id, other_tenant_id
    ):
        """Cross-tenant (non-superadmin) raises 403 and logs."""
        from app.dependencies import _get_user_for_admin

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.tenant_id = other_tenant_id  # different tenant

        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.id = uuid4()
        mock_caller.tenant_id = uuid4()  # yet another tenant

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        with patch("app.dependencies.cross_tenant.set_tenant_context", AsyncMock()), \
             patch("app.dependencies.cross_tenant._log_cross_tenant_attempt") as mock_log:
            mock_db.execute.return_value = mock_result
            with pytest.raises(HTTPException) as exc_info:
                await _get_user_for_admin(
                    user_id, mock_caller, mock_db, method="GET", endpoint=f"/users/{user_id}"
                )

        assert exc_info.value.status_code == 403
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["caller_id"] == mock_caller.id
        assert kwargs["target_id"] == user_id
        assert kwargs["method"] == "GET"

    @pytest.mark.asyncio
    async def test_get_user_for_admin_returns_row_for_superadmin(
        self, user_id, same_tenant_id
    ):
        """Superadmin caller: row fetched, no elevation needed."""
        from app.dependencies import _get_user_for_admin

        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.tenant_id = same_tenant_id

        mock_caller = MagicMock()
        mock_caller.is_superadmin = True
        mock_caller.tenant_id = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user

        mock_db = AsyncMock()
        with patch("app.dependencies.cross_tenant.set_tenant_context", AsyncMock()):
            mock_db.execute.return_value = mock_result
            row = await _get_user_for_admin(
                user_id, mock_caller, mock_db, method="GET", endpoint=f"/users/{user_id}"
            )

        assert row is mock_user

    @pytest.mark.asyncio
    async def test_get_user_for_admin_raises_404_on_missing_row(self, user_id):
        """Non-existent target id returns 404, not 403."""
        from app.dependencies import _get_user_for_admin

        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.tenant_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        with patch("app.dependencies.cross_tenant.set_tenant_context", AsyncMock()), \
             patch("app.dependencies.cross_tenant._log_cross_tenant_attempt") as mock_log:
            mock_db.execute.return_value = mock_result
            with pytest.raises(HTTPException) as exc_info:
                await _get_user_for_admin(
                    user_id, mock_caller, mock_db, method="GET", endpoint=f"/users/{user_id}"
                )

        assert exc_info.value.status_code == 404
        # 404 path: no cross-tenant log.
        mock_log.assert_not_called()


class TestGetTenantForAdmin:
    """T-PRA.12 — _get_tenant_for_admin: same-tenant, cross-tenant 403, superadmin."""

    @pytest.mark.asyncio
    async def test_get_tenant_for_admin_returns_own_tenant(self):
        """Same-tenant non-superadmin caller gets the tenant row."""
        from app.dependencies import _get_tenant_for_admin

        tenant_id = uuid4()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.tenant_id = tenant_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        row = await _get_tenant_for_admin(
            tenant_id, mock_caller, mock_db, method="GET", endpoint=f"/tenants/{tenant_id}"
        )

        assert row is mock_tenant

    @pytest.mark.asyncio
    async def test_get_tenant_for_admin_returns_403_for_cross_tenant(self):
        """Non-superadmin cross-tenant: 403 (NOT 404), with log line, NO DB SELECT."""
        from app.dependencies import _get_tenant_for_admin

        tenant_id = uuid4()
        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.id = uuid4()
        mock_caller.tenant_id = uuid4()  # different

        mock_db = AsyncMock()
        with patch("app.dependencies.cross_tenant._log_cross_tenant_attempt") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                await _get_tenant_for_admin(
                    tenant_id, mock_caller, mock_db, method="GET", endpoint=f"/tenants/{tenant_id}"
                )

        assert exc_info.value.status_code == 403
        # No DB SELECT was issued for the cross-tenant 403 path.
        mock_db.execute.assert_not_called()
        mock_log.assert_called_once()
        kwargs = mock_log.call_args.kwargs
        assert kwargs["caller_id"] == mock_caller.id
        assert kwargs["target_id"] == tenant_id
        assert kwargs["method"] == "GET"

    @pytest.mark.asyncio
    async def test_get_tenant_for_admin_returns_row_for_superadmin(self):
        """Superadmin caller: row fetched regardless of tenant_id match."""
        from app.dependencies import _get_tenant_for_admin

        tenant_id = uuid4()

        mock_tenant = MagicMock()
        mock_tenant.id = tenant_id

        mock_caller = MagicMock()
        mock_caller.is_superadmin = True
        mock_caller.tenant_id = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        row = await _get_tenant_for_admin(
            tenant_id, mock_caller, mock_db, method="GET", endpoint=f"/tenants/{tenant_id}"
        )

        assert row is mock_tenant

    @pytest.mark.asyncio
    async def test_get_tenant_for_admin_raises_404_on_missing_row_when_same_tenant(self):
        """Same-tenant caller: row genuinely absent returns 404."""
        from app.dependencies import _get_tenant_for_admin

        tenant_id = uuid4()
        mock_caller = MagicMock()
        mock_caller.is_superadmin = False
        mock_caller.tenant_id = tenant_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = AsyncMock()
        mock_db.execute.return_value = mock_result
        with pytest.raises(HTTPException) as exc_info:
            await _get_tenant_for_admin(
                tenant_id, mock_caller, mock_db, method="GET", endpoint=f"/tenants/{tenant_id}"
            )

        assert exc_info.value.status_code == 404


class TestUserForAdminWrappers:
    """T-PRA.03 — the three factory wrappers exist and have the right method label."""

    def test_user_for_admin_wrappers_exist(self):
        from app.dependencies import (
            get_user_for_admin_get,
            get_user_for_admin_patch,
            get_user_for_admin_delete,
        )

        assert get_user_for_admin_get is not None
        assert get_user_for_admin_patch is not None
        assert get_user_for_admin_delete is not None
