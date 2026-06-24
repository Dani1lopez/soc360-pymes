from __future__ import annotations

from typing import Any

class AppError(Exception):
    """Excepcion base para todos los servicios de aplicacion"""
    def __init__(self, detail: Any = None, status_code: int = 400) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)

class AuthError(AppError):
    """Excepcion de autenticacion con codigo HTTP y mensaje."""


class ServiceUnavailableError(AppError):
    """Service is unavailable (e.g., Redis down) — fail closed."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(detail=detail or "Servicio temporalmente no disponible", status_code=503)


class TenantError(AppError):
    """Errores del modulo tenants"""


class UserError(AppError):
    """Errores del modulo users"""


class LLMError(AppError):
    """Base for all LLM provider failures."""

    def __init__(self, detail: Any = None, status_code: int = 500) -> None:
        super().__init__(detail, status_code)


class LLMTimeoutError(LLMError):
    """Provider call exceeded configured LLM_TIMEOUT."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(detail, status_code=408)


class LLMRateLimitError(LLMError):
    """Provider returned 429 — not retried automatically."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(detail, status_code=429)


class LLMContentFilterError(LLMError):
    """Provider refused content (safety filter, policy violation)."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(detail, status_code=451)


class LLMResponseError(LLMError):
    """Provider returned error response or unparseable output."""

    def __init__(self, detail: Any = None) -> None:
        super().__init__(detail, status_code=502)


# ── F2 Domain Exceptions ───────────────────────────────────────────────

class AssetError(AppError):
    """Errores del modulo assets (F2)."""


class ScanError(AppError):
    """Errores del modulo scans (F2)."""


class VulnerabilityError(AppError):
    """Errores del modulo vulnerabilities (F2)."""


class ReportError(AppError):
    """Errores del modulo reports (F2)."""
