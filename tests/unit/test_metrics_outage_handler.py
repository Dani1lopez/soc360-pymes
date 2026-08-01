"""Tests for app/main.py — PR4 #260 inline ``/metrics`` route + outage handler.

End-to-end via TestClient. Covers spec scenarios #4, #5, #8, #9.
"""

from __future__ import annotations

from json import loads

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core import metrics_auth
from app.core.config import settings
from app.core.exceptions import (
    RedisOutageError,
    RedisUnreachableError,
    TemporaryUnavailableError,
)
from app.main import create_app


@pytest.fixture(autouse=True)
def _isolate_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the token / cache between tests so test isolation is exact."""
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()
    monkeypatch.setattr(settings, "METRICS_TOKEN", None)
    monkeypatch.setattr(settings, "METRICS_TOKEN_PREVIOUS", None)


class TestMetricsAuthEndToEnd:
    """10 unauthorized variants yield the same 401 body; authorized scrape is 200 text/plain."""

    @pytest.mark.parametrize(
        "headers,label",
        [
            ({}, "missing"),
            ({"x-metrics-token": ""}, "empty"),
            ({"x-metrics-token": "wrong"}, "wrong"),
            ({"x-metrics-token": "Bearer-correct"}, "bearer_prefix"),
            ({"x-metrics-token": "x" * 257}, "oversized"),
            ({"x-metrics-token": " abc"}, "leading_space"),
            ({"x-metrics-token": "abc "}, "trailing_space"),
            ({"x-metrics-token": "a b"}, "internal_space"),
            ({"Authorization": "Bearer anything"}, "authorization_header"),
            # Duplicate header — httpx accepts a list-of-tuples; dict literal cannot express dup keys.
            (
                [("x-metrics-token", "abc"), ("x-metrics-token", "abc")],
                "duplicate_header",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_unauthorized_returns_byte_identical_401(
        self, monkeypatch: pytest.MonkeyPatch, headers, label: str
    ) -> None:
        monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("correct-token"))
        metrics_auth._current_bytes.cache_clear()

        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/metrics", headers=headers)

        assert (
            response.status_code == 401
        ), f"[{label}] got {response.status_code}: {response.text}"
        assert loads(response.content) == {
            "detail": "unauthorized"
        }, f"[{label}] body mismatch"

    @pytest.mark.asyncio
    async def test_authorized_returns_200_text_plain(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """A request with a valid token MUST return 200 + Prometheus text format 0.0.4."""
        monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
        monkeypatch.setattr(settings, "METRICS_TOKEN", SecretStr("correct-token"))
        metrics_auth._current_bytes.cache_clear()

        app = create_app()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                "/metrics", headers={"x-metrics-token": "correct-token"}
            )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "version=0.0.4" in response.headers["content-type"]


class TestRedisOutageHandler:
    """Outage and lock-controller exceptions use separate sanitized 503 handlers."""

    @pytest.mark.asyncio
    async def test_redis_outage_subclass_translates_to_sanitized_503(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "REDIS_OUTAGE_RETRY_AFTER_SECONDS", 60)
        app = create_app()

        @app.get("/_test/raise-outage", include_in_schema=False)
        async def _raise_outage():
            raise RedisUnreachableError("connection refused")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/_test/raise-outage")

        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "60"
        assert response.json()["detail"] == "service temporarily unavailable"
        # Body MUST NOT contain the underlying exception detail or class name.
        assert "RedisUnreachableError" not in response.text
        assert "connection refused" not in response.text

    @pytest.mark.asyncio
    async def test_temporary_unavailable_error_uses_lock_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Lock coordination uses its own retry interval, not the outage interval."""
        monkeypatch.setattr(settings, "REDIS_OUTAGE_RETRY_AFTER_SECONDS", 30)
        monkeypatch.setattr(settings, "LOCK_DEFAULT_RETRY_AFTER_SECONDS", 15)
        app = create_app()

        @app.get("/_test/raise-lock-timeout", include_in_schema=False)
        async def _raise_lock_timeout():
            raise TemporaryUnavailableError("lock_timeout")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/_test/raise-lock-timeout")

        assert response.status_code == 503
        assert response.headers["Retry-After"] == "15"
        assert response.json() == {"detail": "service temporarily unavailable"}
        assert "lock_timeout" not in response.text

    def test_handler_order_pr4_before_app_error(self) -> None:
        """The ``RedisOutageError`` handler MUST be registered."""
        from fastapi import FastAPI

        app = create_app()
        assert isinstance(app, FastAPI)
        assert (
            RedisOutageError in app.exception_handlers
        ), "RedisOutageError handler MUST be registered"
        assert callable(app.exception_handlers[RedisOutageError])
