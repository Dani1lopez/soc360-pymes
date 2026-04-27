from __future__ import annotations

from uuid import uuid4
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException


class TestRedisFailClosed:
    """PR #69 — When Redis is down, auth functions MUST fail closed (503)."""

    @pytest.mark.asyncio
    async def test_login_raises_service_unavailable_when_redis_down(self):
        """login() MUST raise ServiceUnavailableError when Redis is unhealthy."""
        from app.modules.auth import service
        from app.core.exceptions import ServiceUnavailableError

        mock_redis = AsyncMock()
        mock_db = AsyncMock()

        with patch("app.modules.auth.service.check_redis_healthy", return_value=False):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service.login(
                    email="test@example.com",
                    password="any_password",
                    db=mock_db,
                    redis=mock_redis,
                )

        assert exc_info.value.status_code == 503
        assert "no disponible" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_refresh_tokens_raises_service_unavailable_when_redis_down(self):
        """refresh_tokens() MUST raise ServiceUnavailableError when Redis is unhealthy."""
        from app.modules.auth import service
        from app.core.exceptions import ServiceUnavailableError

        mock_redis = AsyncMock()
        mock_db = AsyncMock()

        with patch("app.modules.auth.service.check_redis_healthy", return_value=False):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service.refresh_tokens(
                    refresh_token="some_refresh_token",
                    db=mock_db,
                    redis=mock_redis,
                )

        assert exc_info.value.status_code == 503
        assert "no disponible" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_logout_raises_service_unavailable_when_redis_down(self):
        """logout() MUST raise ServiceUnavailableError when Redis is unhealthy."""
        from app.modules.auth import service
        from app.core.exceptions import ServiceUnavailableError

        mock_redis = AsyncMock()
        mock_db = AsyncMock()

        with patch("app.modules.auth.service.check_redis_healthy", return_value=False):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service.logout(
                    jti="jti-123",
                    refresh_token="some_refresh_token",
                    user_id="user-123",
                    db=mock_db,
                    redis=mock_redis,
                )

        assert exc_info.value.status_code == 503
        assert "no disponible" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_change_password_raises_service_unavailable_when_redis_down(self):
        """change_password() MUST raise ServiceUnavailableError when Redis is unhealthy."""
        from app.modules.auth import service
        from app.core.exceptions import ServiceUnavailableError

        mock_redis = AsyncMock()
        mock_db = AsyncMock()

        with patch("app.modules.auth.service.check_redis_healthy", return_value=False):
            with pytest.raises(ServiceUnavailableError) as exc_info:
                await service.change_password(
                    user_id=uuid4(),
                    current_password="old_password",
                    new_password="NewPassword123!",
                    current_jti="jti-123",
                    db=mock_db,
                    redis=mock_redis,
                )

        assert exc_info.value.status_code == 503
        assert "no disponible" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    async def test_get_current_user_returns_503_when_redis_down(self):
        """get_current_user() MUST raise HTTPException(503) when Redis is unhealthy."""
        from app.core.security import create_access_token

        token, _ = create_access_token(
            user_id=str(uuid4()),
            tenant_id=str(uuid4()),
            role="admin",
            is_superadmin=False,
        )

        mock_redis = AsyncMock()
        mock_db = AsyncMock()

        with patch("app.dependencies.check_redis_healthy", return_value=False):
            from app.dependencies import get_current_user

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    token=token,
                    db=mock_db,
                    redis=mock_redis,
                )

        assert exc_info.value.status_code == 503
        assert "no disponible" in exc_info.value.detail.lower()
