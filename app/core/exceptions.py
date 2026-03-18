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




class TenantError(AppError):
    """Errores del modulo tenants"""