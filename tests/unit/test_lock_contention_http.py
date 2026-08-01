"""HTTP integration coverage for distributed-lock contention."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core import dist_lock
from app.core.dist_lock import acquire_dist_lock
from app.main import create_app


@pytest_asyncio.fixture
async def contention_client(monkeypatch: pytest.MonkeyPatch):
    """Expose a route backed by a Redis key held by another worker."""
    monkeypatch.setattr(
        dist_lock,
        "settings",
        SimpleNamespace(LOCK_KEY_SECRET=SecretStr("http contention secret")),
    )
    monkeypatch.setattr(dist_lock.random, "uniform", lambda _low, _high: 0.0)

    app = create_app()
    redis = FakeRedis()
    key = dist_lock.build_lock_key("scan_start_lock", "tenant-1", "asset-1")
    await redis.set(key, "another-worker", nx=True, px=30_000)

    @app.get("/_test/lock-contention", include_in_schema=False)
    async def _lock_contention() -> dict[str, str]:
        async with acquire_dist_lock(
            flow_id="scan_start_lock",
            tenant_id="tenant-1",
            asset_id="asset-1",
            ttl_seconds=30,
            operation="scan_start",
            wait_timeout_seconds=0.01,
            redis=redis,
        ):
            return {"status": "acquired"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client

    await redis.aclose()


@pytest.mark.asyncio
async def test_lock_contention_is_translated_at_http_boundary(
    contention_client: AsyncClient,
) -> None:
    response = await contention_client.get("/_test/lock-contention")

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == "15"


@pytest.mark.asyncio
async def test_lock_contention_does_not_expose_lock_detail(
    contention_client: AsyncClient,
) -> None:
    response = await contention_client.get("/_test/lock-contention")

    assert "lock_timeout" not in response.text
    assert "TemporaryUnavailableError" not in response.text
