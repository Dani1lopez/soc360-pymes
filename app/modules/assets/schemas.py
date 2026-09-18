"""Pydantic schemas for the Assets domain (Slice 1 — F2).

This module is the single source of truth for the public Assets API
contract. It defines:

* :class:`AssetType` — the six canonical asset_type values.
* Discriminated-union create schemas (one per asset type).
* :class:`AssetUpdate` for partial PATCH.
* :class:`AssetResponse` — the response whitelist (exactly six fields).
* :class:`AssetListResponse` — the list+pagination envelope.

The module imports ``AssetType`` from ``app.event_schemas`` so the event
payloads share the same Literal definition (single source of truth).
Validators for the *semantic* value of each type live in
``app.modules.assets.service`` (D-004) so Pydantic only enforces shape,
discriminator, and length.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.event_schemas import AssetType
from app.modules.assets.models import Asset

# ---------------------------------------------------------------------------
# Re-export AssetType so callers can use this module as the canonical import.
# ---------------------------------------------------------------------------
__all__ = [
    "AssetCreateBase",
    "AssetCreateRequest",
    "AssetListResponse",
    "AssetResponse",
    "AssetType",
    "AssetUpdate",
    "CloudResourceAssetCreate",
    "DomainAssetCreate",
    "HostnameAssetCreate",
    "IpAssetCreate",
    "SubnetAssetCreate",
    "WebAppAssetCreate",
]


# ---------------------------------------------------------------------------
# T3.1 — Discriminated-union create schemas
# ---------------------------------------------------------------------------
# The public ``type`` field translates internally to ``Asset.asset_type``;
# the column name is intentionally NOT exposed as ``asset_type``.
class AssetCreateBase(BaseModel):
    """Common request body shared across the six create branches.

    ``extra="forbid"`` rejects unknown keys at the API boundary so the
    service can rely on the parsed shape. Length and shape validation
    only — semantic validation is delegated to the service layer.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    value: str = Field(min_length=1, max_length=255)


class IpAssetCreate(AssetCreateBase):
    type: Literal["ip"] = "ip"


class DomainAssetCreate(AssetCreateBase):
    type: Literal["domain"] = "domain"


class HostnameAssetCreate(AssetCreateBase):
    type: Literal["hostname"] = "hostname"


class WebAppAssetCreate(AssetCreateBase):
    type: Literal["web_app"] = "web_app"


class SubnetAssetCreate(AssetCreateBase):
    type: Literal["subnet"] = "subnet"


class CloudResourceAssetCreate(AssetCreateBase):
    type: Literal["cloud_resource"] = "cloud_resource"


# Union type used by the router — the Field(discriminator="type") is bound
# onto this Annotated alias so Pydantic dispatches on the literal ``type``.
AssetCreateRequest = Annotated[
    IpAssetCreate
    | DomainAssetCreate
    | HostnameAssetCreate
    | WebAppAssetCreate
    | SubnetAssetCreate
    | CloudResourceAssetCreate,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# T3.2 — PATCH schema (partial update)
# ---------------------------------------------------------------------------
class AssetUpdate(BaseModel):
    """Partial update payload.

    Both fields are optional; the service combines the supplied values
    with the persisted state and validates the resulting pair. Unknown
    keys are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    type: AssetType | None = None
    value: str | None = Field(default=None, min_length=1, max_length=255)


# ---------------------------------------------------------------------------
# T3.3 — Response whitelist (exactly six fields)
# ---------------------------------------------------------------------------
class AssetResponse(BaseModel):
    """The public Assets response.

    Only six fields are exposed. The ``from_orm_instance`` helper performs
    the explicit ``asset_type`` → ``type`` mapping so the ORM column name
    never leaks (D-009).
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )

    id: UUID
    type: AssetType
    value: str
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_instance(cls, asset: Asset) -> AssetResponse:
        """Build an :class:`AssetResponse` from an ORM :class:`Asset`.

        Performs the explicit ``asset_type`` → ``type`` rename so the
        column name is not exposed on the wire. Any other ORM attribute
        (status, asset_metadata, created_by_user_id, raw_input, …) is
        dropped by construction.
        """
        data: dict[str, Any] = {
            "id": asset.id,
            "type": asset.asset_type,
            "value": asset.value,
            "tenant_id": asset.tenant_id,
            "created_at": asset.created_at,
            "updated_at": asset.updated_at,
        }
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# T3.4 — List response envelope
# ---------------------------------------------------------------------------
class AssetListResponse(BaseModel):
    """Paginated list response (items + total + pagination metadata)."""

    items: list[AssetResponse]
    total: int
    limit: int
    offset: int
