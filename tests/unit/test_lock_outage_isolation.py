"""HTTP integration coverage for Redis outage and lock contention isolation."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import RedisUnreachableError, TemporaryUnavailableError
from app.main import create_app


@pytest_asyncio.fixture
async def error_client(monkeypatch: pytest.MonkeyPatch):
    """Expose one route for each 503 domain at the HTTP boundary."""
    monkeypatch.setattr(settings, "REDIS_OUTAGE_RETRY_AFTER_SECONDS", 30)
    monkeypatch.setattr(settings, "LOCK_DEFAULT_RETRY_AFTER_SECONDS", 15)
    app = create_app()

    @app.get("/_test/redis-outage", include_in_schema=False)
    async def _redis_outage() -> None:
        raise RedisUnreachableError("connection refused")

    @app.get("/_test/lock-unavailable", include_in_schema=False)
    async def _lock_unavailable() -> None:
        raise TemporaryUnavailableError("lock_timeout")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_redis_outage_keeps_outage_retry_after(error_client: AsyncClient) -> None:
    response = await error_client.get("/_test/redis-outage")

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == "30"


@pytest.mark.asyncio
async def test_lock_unavailable_uses_contention_retry_after(
    error_client: AsyncClient,
) -> None:
    response = await error_client.get("/_test/lock-unavailable")

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == "15"


@pytest.mark.asyncio
async def test_outage_and_contention_are_distinguishable(
    error_client: AsyncClient,
) -> None:
    outage = await error_client.get("/_test/redis-outage")
    contention = await error_client.get("/_test/lock-unavailable")

    assert outage.status_code == contention.status_code == 503
    assert outage.json() == contention.json()
    assert outage.headers["Retry-After"] != contention.headers["Retry-After"]
