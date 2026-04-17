from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.core.types import EmailStr


class RoleEnum(str, Enum):
    viewer = "viewer"
    analyst = "analyst"
    ingestor = "ingestor"
    admin = "admin"
    superadmin = "superadmin"


class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Email unico del usuario")
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: RoleEnum = Field(..., description="Rol del usuario")
    tenant_id: uuid.UUID | None = Field(None, description="None solo si is_superadmin=True")
    is_superadmin: bool = Field(False)
    
    @model_validator(mode="after")
    def check_superadmin_consistency(self) -> UserCreate:
        if self.is_superadmin and self.tenant_id is not None:
            raise ValueError("Un superadmin no puede pertenecer a un tenant")
        if not self.is_superadmin and self.tenant_id is None:
            raise ValueError("Un usuario normal debe tener tenant_id")
        if self.is_superadmin and self.role != RoleEnum.superadmin:
            raise ValueError("is_superadmin=True requiere role='superadmin'")
        return self


class UserUpdate(BaseModel):
    email: EmailStr | None = Field(None, max_length=255)
    full_name: str | None = Field(None, min_length=1, max_length=255)
    role: RoleEnum | None = None
    is_active: bool | None = None
    
    @model_validator(mode="after")
    def check_role_not_superadmin(self) -> UserUpdate:
        if self.role == RoleEnum.superadmin:
            raise ValueError(
                "No se puede asignar role='superadmin' via update. "
                "Los superadmins se crean directamente."
            )
        return self


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    email: str
    full_name: str
    role: RoleEnum
    is_active: bool
    is_superadmin: bool
    created_at: datetime
    updated_at: datetime