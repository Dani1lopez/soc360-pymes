"""Tests for app/core/middleware.py — HTTPSRedirectMiddleware."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import settings


class TestHTTPSRedirectMiddleware:
    """Verify HTTPSRedirectMiddleware redirects conditionally."""

    @pytest.fixture
    def mock_app(self):
        async def _app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"ok",
                }
            )

        return _app

    @pytest.fixture
    def middleware(self, mock_app):
        from app.core.middleware import HTTPSRedirectMiddleware

        return HTTPSRedirectMiddleware(mock_app)

    @pytest.mark.asyncio
    async def test_redirects_http_to_https_in_production(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """HTTP requests in production MUST receive 307 redirect to HTTPS."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        calls = []

        async def _send(message):
            calls.append(message)

        scope = {
            "type": "http",
            "scheme": "http",
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [[b"host", b"api.example.com"]],
        }

        await middleware(scope, AsyncMock(), _send)

        start = calls[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 307

        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert headers["location"].startswith("https://")

    @pytest.mark.asyncio
    async def test_no_redirect_when_https(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """Requests already using HTTPS MUST NOT be redirected."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        calls = []

        async def _send(message):
            calls.append(message)

        scope = {
            "type": "http",
            "scheme": "https",
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [[b"host", b"api.example.com"]],
        }

        await middleware(scope, AsyncMock(), _send)

        start = calls[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_no_redirect_in_development(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """HTTP requests in development MUST NOT be redirected."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")

        calls = []

        async def _send(message):
            calls.append(message)

        scope = {
            "type": "http",
            "scheme": "http",
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [[b"host", b"localhost"]],
        }

        await middleware(scope, AsyncMock(), _send)

        start = calls[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_respects_x_forwarded_proto_https(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """Requests with X-Forwarded-Proto: https MUST NOT be redirected."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["10.0.0.1"])

        calls = []

        async def _send(message):
            calls.append(message)

        scope = {
            "type": "http",
            "scheme": "http",
            "client": ["10.0.0.1", 54321],
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [
                [b"host", b"api.example.com"],
                [b"x-forwarded-proto", b"https"],
            ],
        }

        await middleware(scope, AsyncMock(), _send)

        start = calls[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_rejects_x_forwarded_proto_from_untrusted_client(self, middleware, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "TRUSTED_PROXIES", ["10.0.0.1"])

        calls = []

        async def _send(message):
            calls.append(message)

        scope = {
            "type": "http",
            "scheme": "http",
            "client": ["192.168.1.99", 54321],
            "method": "GET",
            "path": "/api/v1/users",
            "headers": [
                [b"host", b"api.example.com"],
                [b"x-forwarded-proto", b"https"],
            ],
        }

        await middleware(scope, AsyncMock(), _send)

        start = calls[0]
        assert start["type"] == "http.response.start"
        assert start["status"] == 307
