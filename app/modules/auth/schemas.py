from __future__ import annotations

import re

from pydantic import BaseModel, field_validator


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = str(v).strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Formato de email inválido")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_strength(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("La contraseña debe de tener al menos 12 caracteres")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Debe de contener al menos una mayuscula")
        if not re.search(r"[a-z]", v):
            raise ValueError("Debe de contenener al menos una minuscula")
        if not re.search(r"\d", v):
            raise ValueError("Debe de contener algun numero")
        return v