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