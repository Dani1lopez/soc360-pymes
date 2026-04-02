from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ScanLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    daily_max: int = Field(default=5, gt=0)
    concurrent_max: int = Field(default=1, gt=0)


class TenantSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    notification_email: EmailStr | None = None
    scan_schedule: str = "0 2 * * *"
    severity_threshold: Literal["critical", "high", "medium", "low"] = "medium"
    timezone: str = "Europe/Madrid"
    scan_limits: ScanLimits = ScanLimits()
    log_buffer_max: int = Field(default=500, gt=0)
    baseline_reset_requested: bool = False


class TenantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str
    slug: str | None = None
    plan: Literal["free", "starter", "pro", "enterprise"] = "free"
    max_assets: int = 10
    settings: TenantSettings = TenantSettings()
    
    @field_validator("slug")
    @classmethod
    def slug_must_be_valid(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9]+(?:-[a-z0-9]+)*$", v):
            raise ValueError(
                "El slug solo puede contener letras minusculas, numeros y guiones"
            )
        if len(v) < 3 or len(v) > 100:
            raise ValueError("El slug debe de tener entre 3 y 100 caracteres")
        return v
    
    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre no puede estar vacio")
        return v
    
    @field_validator("max_assets")
    @classmethod
    def max_assets_must_be_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                "max_assets debe de ser al menos 1"
            )
        return v


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    name: str | None = None
    plan: Literal["free", "starter", "pro", "enterprise"] | None = None
    is_active: bool | None = None
    max_assets: int | None = None
    settings: TenantSettings | None = None
    
    @field_validator("name")
    @classmethod
    def name_must_be_not_blank(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("El nombre no puede estar vacio.")
        return v
    
    @field_validator("max_assets")
    @classmethod
    def max_assets_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("max_assets debe ser al menos 1")
        return v


class TenantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    max_assets: int
    settings: TenantSettings
    created_at: datetime
    updated_at: datetime
    
    @field_validator("settings", mode="before")
    @classmethod
    def settings_default_if_none(cls, v):
        if v is None:
            return {}
        return v

