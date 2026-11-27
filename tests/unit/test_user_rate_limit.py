"""Unit tests for per-user rate limiting (M7)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.rate_limit import UserRateLimiter
from app.core.redis import get_redis
from app.dependencies import auth as auth_deps
from app.dependencies.auth import (
    _enforce_user_rate_limit,
    enforce_enrichment_rate_limit,
    get_current_user,
)
from app.dependencies.db_deps import get_db_with_tenant
from app.modules.enrichment import queries as enrichment_queries
from app.modules.enrichment import router as enrichment_router


@pytest.mark.asyncio
async def test_user_rate_limiter_allows_up_to_limit_and_blocks_next() -> None:
    redis = FakeRedis(decode_responses=True)
    limiter = UserRateLimiter(redis)
    user_id = str(uuid4())

    for idx in range(3):
        res = await limiter.check_and_increment(
            user_id=user_id,
            bucket="mutation",
            limit=3,
            window_seconds=60,
        )
        assert res.allowed is True
        assert res.limit == 3
        assert res.remaining == 3 - (idx + 1)
        assert res.retry_after == 0

    blocked = await limiter.check_and_increment(
        user_id=user_id,
        bucket="mutation",
        limit=3,
        window_seconds=60,
    )
    assert blocked.allowed is False
    assert blocked.remaining == 0
    assert blocked.retry_after >= 1

    ttl = await redis.ttl(f"ratelimit:user:mutation:{user_id}")
    assert 0 < ttl <= 60


@pytest.mark.asyncio
async def test_user_rate_limiter_isolates_users_and_buckets() -> None:
    redis = FakeRedis(decode_responses=True)
    limiter = UserRateLimiter(redis)
    user_a = str(uuid4())
    user_b = str(uuid4())

    assert (await limiter.check_and_increment(user_a, "mutation", 1, 60)).allowed is True
    assert (await limiter.check_and_increment(user_a, "mutation", 1, 60)).allowed is False

    # Different bucket for same user is independent
    assert (await limiter.check_and_increment(user_a, "enrichment", 1, 60)).allowed is True
    # Different user for same bucket is independent
    assert (await limiter.check_and_increment(user_b, "mutation", 1, 60)).allowed is True


@pytest.mark.asyncio
async def test_enforce_user_rate_limit_raises_429_with_retry_after() -> None:
    redis = FakeRedis(decode_responses=True)
    user_id = uuid4()

    await _enforce_user_rate_limit(user_id, "mutation", 1, 45, redis)
    with pytest.raises(HTTPException) as exc_info:
        await _enforce_user_rate_limit(user_id, "mutation", 1, 45, redis)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_enforce_user_rate_limit_respects_disabled_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis(decode_responses=True)
    user_id = uuid4()
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)

    await _enforce_user_rate_limit(user_id, "mutation", 1, 60, redis)
    await _enforce_user_rate_limit(user_id, "mutation", 1, 60, redis)


@pytest.mark.asyncio
async def test_enforce_enrichment_rate_limit_blocks_after_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis(decode_responses=True)
    user = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(settings, "RATE_LIMIT_ENRICHMENT_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENRICHMENT_WINDOW_SECONDS", 60)

    await enforce_enrichment_rate_limit(current_user=user, redis=redis)
    await enforce_enrichment_rate_limit(current_user=user, redis=redis)
    with pytest.raises(HTTPException) as exc_info:
        await enforce_enrichment_rate_limit(current_user=user, redis=redis)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_get_current_user_rate_limits_mutations_and_ignores_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis(decode_responses=True)
    user_id = uuid4()
    tenant_id = uuid4()

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_USER_MUTATION_REQUESTS", 2)
    monkeypatch.setattr(settings, "RATE_LIMIT_USER_MUTATION_WINDOW_SECONDS", 60)
    monkeypatch.setattr(
        auth_deps,
        "decode_access_token",
        lambda _token: {
            "sub": str(user_id),
            "jti": "jti-1",
            "credential_version": 0,
        },
    )
    monkeypatch.setattr(auth_deps, "check_redis_healthy", AsyncMock(return_value=True))
    monkeypatch.setattr(auth_deps, "is_token_revoked", AsyncMock(return_value=False))
    monkeypatch.setattr(auth_deps, "set_tenant_context", AsyncMock())

    user_obj = SimpleNamespace(
        id=user_id,
        is_active=True,
        is_superadmin=False,
        tenant_id=tenant_id,
        credential_version=0,
    )
    tenant_obj = SimpleNamespace(is_active=True)
    row = SimpleNamespace(User=user_obj, Tenant=tenant_obj)
    select_result = MagicMock()
    select_result.one_or_none.return_value = row

    db = MagicMock()
    db.execute = AsyncMock(side_effect=lambda *_args, **_kwargs: select_result)

    get_req = Request({"type": "http", "method": "GET", "headers": []})
    for _ in range(3):
        u = await get_current_user(token="tok", db=db, redis=redis, request=get_req)
        assert u is user_obj
    assert await redis.get(f"ratelimit:user:mutation:{user_id}") is None

    post_req = Request({"type": "http", "method": "POST", "headers": []})
    await get_current_user(token="tok", db=db, redis=redis, request=post_req)
    await get_current_user(token="tok", db=db, redis=redis, request=post_req)
    with pytest.raises(HTTPException) as exc_info:
        await get_current_user(token="tok", db=db, redis=redis, request=post_req)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) >= 1


@pytest.mark.asyncio
async def test_enrichment_routes_enforce_enrichment_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = FakeRedis(decode_responses=True)
    user_id = uuid4()
    tenant_id = uuid4()
    vuln_id = uuid4()
    scan_id = uuid4()

    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENRICHMENT_REQUESTS", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENRICHMENT_WINDOW_SECONDS", 60)
    monkeypatch.setattr(
        enrichment_queries,
        "visible_vulnerability",
        AsyncMock(return_value=SimpleNamespace(id=vuln_id, tenant_id=tenant_id)),
    )
    monkeypatch.setattr(
        enrichment_queries,
        "visible_scan",
        AsyncMock(return_value=SimpleNamespace(id=scan_id, tenant_id=tenant_id)),
    )
    monkeypatch.setattr(
        enrichment_queries,
        "tenant_level",
        AsyncMock(return_value="basic"),
    )
    monkeypatch.setattr(
        enrichment_queries,
        "scan_pending",
        AsyncMock(return_value=([], 0)),
    )

    fake_user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        is_superadmin=False,
        role="admin",
    )

    test_app = FastAPI()
    test_app.include_router(enrichment_router.router)
    test_app.dependency_overrides[get_current_user] = lambda: fake_user
    test_app.dependency_overrides[get_redis] = lambda: redis
    test_app.dependency_overrides[get_db_with_tenant] = lambda: MagicMock()
    test_app.dependency_overrides[enrichment_router.get_enrichment_enqueuer] = (
        lambda: AsyncMock(return_value=True)
    )

    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as client:
        first_vuln = await client.post(f"/vulnerabilities/{vuln_id}/enrichment")
        assert first_vuln.status_code == 202
        second_vuln = await client.post(f"/vulnerabilities/{vuln_id}/enrichment")
        assert second_vuln.status_code == 429
        assert int(second_vuln.headers["Retry-After"]) >= 1

        await redis.flushall()

        first_scan = await client.post(f"/scans/{scan_id}/enrichment")
        assert first_scan.status_code == 202
        second_scan = await client.post(f"/scans/{scan_id}/enrichment")
        assert second_scan.status_code == 429
        assert int(second_scan.headers["Retry-After"]) >= 1
