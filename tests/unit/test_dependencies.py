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

        with patch("app.dependencies.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.set_tenant_context", AsyncMock()) as mock_set_ctx:
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

        with patch("app.dependencies.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.set_tenant_context", AsyncMock()) as mock_set_ctx:
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

        with patch("app.dependencies.decode_access_token", return_value=valid_token_payload), \
             patch("app.dependencies.check_redis_healthy", AsyncMock(return_value=True)), \
             patch("app.dependencies.is_token_revoked", AsyncMock(return_value=False)), \
             patch("app.dependencies.set_tenant_context", AsyncMock()) as mock_set_ctx:
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
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
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
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instance1 = await get_event_bus()
            instance2 = await get_event_bus()
            assert instance1 is instance2
        await mock_redis.aclose()

    @pytest.mark.asyncio
    async def test_get_event_bus_singleton_across_multiple_calls(self):
        """get_event_bus() singleton MUST hold across >2 calls."""
        mock_redis = FakeRedis()
        with patch("app.dependencies.get_redis_client", AsyncMock(return_value=mock_redis)):
            from app.dependencies import get_event_bus

            instances = [await get_event_bus() for _ in range(5)]
            assert all(inst is instances[0] for inst in instances)
        await mock_redis.aclose()
