"""Unit tests for F1: skip per-email Redis rate-limit keys for non-existent accounts."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import AuthError
from app.core.rate_limit import _EMAIL_PREFIX, _IP_PREFIX, RateLimiter
from app.core.redis import get_redis
from app.modules.auth import router as auth_router
from app.modules.auth import service as auth_service


@pytest.mark.asyncio
async def test_record_failure_with_record_email_false_only_writes_ip_key() -> None:
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)

    status = await limiter.record_failure(
        "198.51.100.10", "ghost@example.com", record_email=False
    )

    keys = await redis.keys("*")
    assert keys == [f"{_IP_PREFIX}198.51.100.10"]
    assert not any(k.startswith(_EMAIL_PREFIX) for k in keys)
    assert status.failures == 1


@pytest.mark.asyncio
async def test_record_failure_default_writes_both_ip_and_email_keys() -> None:
    redis = FakeRedis(decode_responses=True)
    limiter = RateLimiter(redis)

    await limiter.record_failure("198.51.100.11", "real@example.com")

    keys = await redis.keys("*")
    assert f"{_IP_PREFIX}198.51.100.11" in keys
    assert any(k.startswith(_EMAIL_PREFIX) for k in keys)


def _make_auth_app(fake_redis: FakeRedis) -> FastAPI:
    app = FastAPI()
    app.include_router(auth_router.router, prefix="/api/v1")

    async def _override_db():
        yield MagicMock()

    async def _override_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_redis] = _override_redis
    return app


@pytest.mark.asyncio
async def test_login_unknown_user_creates_no_email_key_in_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(
        auth_service,
        "login",
        AsyncMock(
            side_effect=AuthError(
                status_code=401,
                detail="Credenciales incorrectas",
                record_email=False,
            )
        ),
    )

    app = _make_auth_app(fake_redis)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "unknown@example.com", "password": "WrongPassword123!"},
        )

    assert resp.status_code == 401
    keys = await fake_redis.keys("*")
    assert len(keys) == 1
    assert keys[0].startswith(_IP_PREFIX)
    assert not any(k.startswith(_EMAIL_PREFIX) for k in keys)


@pytest.mark.asyncio
async def test_login_existing_user_wrong_password_creates_email_key_in_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(
        auth_service,
        "login",
        AsyncMock(
            side_effect=AuthError(
                status_code=401,
                detail="Credenciales incorrectas",
            )
        ),
    )

    app = _make_auth_app(fake_redis)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "existing@example.com", "password": "WrongPassword123!"},
        )

    assert resp.status_code == 401
    keys = await fake_redis.keys("*")
    assert any(k.startswith(_IP_PREFIX) for k in keys)
    assert any(k.startswith(_EMAIL_PREFIX) for k in keys)


@pytest.mark.asyncio
async def test_service_login_unknown_user_sets_record_email_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_service, "check_redis_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(auth_service, "set_tenant_context", AsyncMock())
    monkeypatch.setattr(
        auth_service,
        "_get_active_user",
        AsyncMock(side_effect=AuthError(status_code=401, detail="Credenciales incorrectas")),
    )
    monkeypatch.setattr(auth_service, "verify_password_async", AsyncMock(return_value=False))

    with pytest.raises(AuthError) as exc_info:
        await auth_service.login(
            email="nobody@example.com",
            password="WrongPassword123!",
            db=MagicMock(),
            redis=MagicMock(),
        )

    assert exc_info.value.status_code == 401
    assert exc_info.value.record_email is False
