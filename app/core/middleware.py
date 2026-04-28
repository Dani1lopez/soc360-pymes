from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.core.config import settings

NOSNIFF = "nosniff"
XFRAME_DENY = "DENY"
CSP_SELF_ONLY = "default-src 'self'"
HSTS_MAX_AGE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = NOSNIFF
        response.headers["X-Frame-Options"] = XFRAME_DENY
        response.headers["Content-Security-Policy"] = CSP_SELF_ONLY
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = HSTS_MAX_AGE
        return response


class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if settings.ENVIRONMENT != "production":
            return await call_next(request)

        if settings.TRUSTED_PROXIES and request.client and request.client.host in settings.TRUSTED_PROXIES:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        else:
            proto = request.url.scheme
        if proto == "http":
            https_url = str(request.url.replace(scheme="https"))
            return RedirectResponse(url=https_url, status_code=307)

        return await call_next(request)
