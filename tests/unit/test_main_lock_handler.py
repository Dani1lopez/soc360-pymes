"""Tests for the HTTP translation of lock coordination failures."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.exceptions import TemporaryUnavailableError
from app.core.exceptions import RedisOutageError
from app.main import create_app


@pytest.mark.asyncio
@pytest.mark.parametrize("detail", ["lock_timeout", "lock_reentry", None])
async def test_temporary_unavailable_returns_sanitized_503_with_retry_after(
    monkeypatch: pytest.MonkeyPatch, detail: str | None
) -> None:
    monkeypatch.setattr(settings, "LOCK_DEFAULT_RETRY_AFTER_SECONDS", 15)
    app = create_app()

    @app.get("/_test/raise-lock", include_in_schema=False)
    async def _raise_lock() -> None:
        raise TemporaryUnavailableError(detail)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/_test/raise-lock")

    assert response.status_code == 503
    assert response.json() == {"detail": "service temporarily unavailable"}
    assert response.headers["Retry-After"] == "15"
    assert detail is None or detail not in response.text


@pytest.mark.asyncio
async def test_temporary_unavailable_handler_uses_configured_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LOCK_DEFAULT_RETRY_AFTER_SECONDS", 9)
    app = create_app()

    @app.get("/_test/raise-lock-configured", include_in_schema=False)
    async def _raise_lock_configured() -> None:
        raise TemporaryUnavailableError("lock_timeout")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/_test/raise-lock-configured")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "9"


def test_lock_handler_is_registered_after_redis_outage_handler() -> None:
    app = create_app()

    handlers = list(app.exception_handlers)
    assert RedisOutageError in app.exception_handlers
    assert TemporaryUnavailableError in app.exception_handlers
    assert handlers.index(TemporaryUnavailableError) > handlers.index(RedisOutageError)
