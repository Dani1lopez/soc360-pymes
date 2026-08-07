from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import AuthError, RedisOutageError
from app.core.database import get_db
from app.core.redis import get_redis
from app.dependencies.auth import get_current_user
from app.core.security import create_access_token
from app.main import create_app


def _build_app() -> FastAPI:
    app = create_app()

    async def override_db():
        return MagicMock()

    async def override_redis():
        return MagicMock()

    async def override_current_user():
        return SimpleNamespace(id="user-1", current_jti="jti-1")

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = override_redis
    app.dependency_overrides[get_current_user] = override_current_user
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "method_name", "request_kwargs"),
    [
        ("/api/v1/auth/login", "login", {"json": {"email": "u@example.com", "password": "Password123!"}}),
        ("/api/v1/auth/refresh", "refresh_tokens", {"cookies": {"refresh_token": "refresh-1"}}),
        ("/api/v1/auth/logout", "logout", {}),
        (
            "/api/v1/auth/change-password",
            "change_password",
            {"json": {"current_password": "OldPassword123!", "new_password": "NewPassword123!"}},
        ),
    ],
)
async def test_auth_router_re_raises_typed_outage_to_global_handler(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    method_name: str,
    request_kwargs: dict,
) -> None:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    app = _build_app()
    service_method = AsyncMock(side_effect=RedisOutageError("database credential leaked"))

    with patch.object(__import__("app.modules.auth.service", fromlist=[method_name]), method_name, service_method):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(path, **request_kwargs)

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == str(settings.REDIS_OUTAGE_RETRY_AFTER_SECONDS)
    assert "database credential leaked" not in response.text
    service_method.assert_awaited_once()


@pytest.mark.asyncio
async def test_auth_router_still_converts_sub_500_app_errors() -> None:
    from app.modules.auth import service

    app = _build_app()
    service_method = AsyncMock(
        side_effect=AuthError(status_code=401, detail="Credenciales incorrectas")
    )

    with patch.object(service, "login", service_method):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "u@example.com", "password": "wrong"},
            )

    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales incorrectas"}
    assert "Retry-After" not in response.headers
    service_method.assert_awaited_once()


@pytest.mark.asyncio
async def test_current_user_health_failure_uses_global_service_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.dependencies.auth.check_redis_healthy", AsyncMock(return_value=False)
    )
    app = _build_app()
    app.dependency_overrides.pop(get_current_user)

    @app.get("/_test/current-user")
    async def _current_user_route(user=Depends(get_current_user)):
        return {"user_id": str(user.id)}

    token, _ = create_access_token(
        user_id=str(uuid4()),
        tenant_id=str(uuid4()),
        role="admin",
        is_superadmin=False,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/_test/current-user", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == str(settings.REDIS_OUTAGE_RETRY_AFTER_SECONDS)


@pytest.mark.asyncio
async def test_login_masked_rate_limit_precheck_stays_generic_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.auth import router as auth_router
    from app.modules.auth import service

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    app = _build_app()
    service_login = AsyncMock()
    rate_limiter = SimpleNamespace(
        check=AsyncMock(return_value=SimpleNamespace(is_locked=True)),
        record_failure=AsyncMock(),
        record_success=AsyncMock(),
    )

    async def override_rate_limiter():
        return rate_limiter

    app.dependency_overrides[auth_router._get_rate_limiter] = override_rate_limiter
    with patch.object(service, "login", service_login):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "u@example.com", "password": "wrong"},
            )

    assert response.status_code == 401
    assert response.json() == {"detail": "Credenciales incorrectas"}
    assert "Retry-After" not in response.headers
    service_login.assert_not_awaited()
