"""Integration tests for security headers — requires live app."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport

from app.core.config import settings
from app.main import create_app


class TestSecurityHeadersIntegration:
    """End-to-end security header verification via TestClient."""

    @pytest.mark.asyncio
    async def test_security_headers_present_in_development(self):
        """Even in dev mode, nosniff/XFO/CSP headers should appear."""
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("content-security-policy") == "default-src 'self'"
        # HSTS should NOT be present in development
        assert "strict-transport-security" not in resp.headers

    @pytest.mark.asyncio
    async def test_docs_available_in_development(self):
        """Swagger docs should be accessible in development."""
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/docs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_stack_order_security_headers_applied(self):
        """All security headers should be present on any endpoint."""
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
        
        # All security headers should be present
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("content-security-policy") == "default-src 'self'"
        
        # CORS headers should be present (from CORSMiddleware)
        # Note: CORS headers only appear on cross-origin requests or preflight

    @pytest.mark.asyncio
    async def test_security_headers_on_auth_endpoints(self):
        """Security headers should be present on auth endpoints too."""
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/auth/login",
                json={"email": "test@test.com", "password": "wrong"},
            )
        
        # Security headers should be present even on 401 responses
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("content-security-policy") == "default-src 'self'"

    @pytest.mark.asyncio
    async def test_security_headers_on_404(self):
        """Security headers should be present on 404 responses."""
        app = create_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/nonexistent")
        
        assert resp.status_code == 404
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
