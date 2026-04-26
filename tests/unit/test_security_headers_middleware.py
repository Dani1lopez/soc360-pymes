"""Tests for app/core/middleware.py — SecurityHeadersMiddleware."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.core.config import settings


class TestSecurityHeadersMiddleware:
    """Verify SecurityHeadersMiddleware injects hardening headers conditionally."""

    @pytest.fixture
    def mock_app(self):
        async def _app(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [[b"content-type", b"application/json"]],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"ok": true}',
                }
            )

        return _app

    @pytest.fixture
    def middleware(self, mock_app):
        from app.core.middleware import SecurityHeadersMiddleware

        return SecurityHeadersMiddleware(mock_app)

    @pytest.mark.asyncio
    async def test_injects_x_content_type_options_nosniff(self, middleware):
        """Response MUST include X-Content-Type-Options: nosniff."""
        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        start = calls[0]
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert headers["x-content-type-options"] == "nosniff"

    @pytest.mark.asyncio
    async def test_injects_x_frame_options_deny(self, middleware):
        """Response MUST include X-Frame-Options: DENY."""
        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        start = calls[0]
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert headers["x-frame-options"] == "DENY"

    @pytest.mark.asyncio
    async def test_injects_csp_default_src_self(self, middleware):
        """Response MUST include Content-Security-Policy: default-src 'self'."""
        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        start = calls[0]
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert headers["content-security-policy"] == "default-src 'self'"

    @pytest.mark.asyncio
    async def test_injects_hsts_in_production(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """Response MUST include Strict-Transport-Security when ENVIRONMENT=production."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")

        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        start = calls[0]
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert "strict-transport-security" in headers

    @pytest.mark.asyncio
    async def test_no_hsts_in_development(self, middleware, monkeypatch: pytest.MonkeyPatch):
        """Response MUST NOT include Strict-Transport-Security when ENVIRONMENT=development."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")

        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        start = calls[0]
        headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
        assert "strict-transport-security" not in headers

    @pytest.mark.asyncio
    async def test_preserves_response_body(self, middleware):
        """Middleware MUST NOT alter the response body."""
        calls = []

        async def _send(message):
            calls.append(message)

        await middleware(
            {"type": "http", "method": "GET", "path": "/", "headers": []},
            AsyncMock(),
            _send,
        )

        body_msg = calls[1]
        assert body_msg["type"] == "http.response.body"
        assert body_msg["body"] == b'{"ok": true}'
