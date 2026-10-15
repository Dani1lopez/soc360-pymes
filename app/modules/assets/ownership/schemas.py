"""HTTP contracts for asset ownership declarations (H2)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OwnershipDeclarationRequest(BaseModel):
    """What the caller declares. Only the method is caller-controlled."""

    # ``declaration`` is the self-declaration that covers assets where no
    # technical check is possible; the other two start a challenge (H2-T6).
    method: Literal["declaration", "dns_txt", "http_file"] = "declaration"


class OwnershipDeclarationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    tenant_id: uuid.UUID
    method: str
    status: str
    token: str
    declared_by_user_id: uuid.UUID | None
    verified_at: datetime | None
    resolved_fingerprint: str | None
    created_at: datetime
    updated_at: datetime


class OwnershipDeclarationListResponse(BaseModel):
    items: list[OwnershipDeclarationResponse]
    total: int
