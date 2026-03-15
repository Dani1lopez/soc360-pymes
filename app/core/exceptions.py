from __future__ import annotations

from typing import Any


class AuthError(Exception):
    """Excepcion de autenticacion con codigo HTTP y mensaje."""
    def __init__(self, status_code: int, detail: Any = None) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)