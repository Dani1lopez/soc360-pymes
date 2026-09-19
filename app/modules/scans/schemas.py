"""Pydantic schemas for the Scans domain (Slice 2 - F2).

This module is the single source of truth for the public Scans API contract:

* :class:`ScanType` - the four canonical scan types, re-exported from
  ``app.event_schemas`` so the event payloads and this module cannot drift.
* A discriminated-union create schema, one branch per scan type, each with its
  own strict ``config`` model.
* :class:`ScanUpdate` for partial PATCH.
* :class:`ScanResponse` - the response whitelist of exactly eleven fields.
* :class:`ScanListResponse` - the paginated envelope.

Pydantic enforces shape, the discriminator and the required config keys.
SEMANTIC validation of a config value (a check identifier being non-empty, a
path starting with ``/``) lives in ``app.modules.scans.service`` so the error
messages have a single home, mirroring the Assets slice.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.event_schemas import ScanStatus, ScanType
from app.modules.scans.models import Scan

__all__ = [
    "DiscoveryConfig",
    "DiscoveryScanCreate",
    "FullConfig",
    "FullScanCreate",
    "ScanCreateBase",
    "ScanCreateRequest",
    "ScanListResponse",
    "ScanResponse",
    "ScanStatus",
    "ScanType",
    "ScanUpdate",
    "VulnerabilityConfig",
    "VulnerabilityScanCreate",
    "WebConfig",
    "WebScanCreate",
]


# ---------------------------------------------------------------------------
# Per-type config models. Strict: an unknown key is rejected rather than
# silently stored, so a typo cannot become persisted configuration.
# ---------------------------------------------------------------------------
class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_discovery: bool


class VulnerabilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checks: list[str] = Field(min_length=1)


class WebConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] = Field(min_length=1)


class FullConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_discovery: bool
    checks: list[str] = Field(min_length=1)
    paths: list[str] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Create: a discriminated union on the public ``type`` field.
# ---------------------------------------------------------------------------
class ScanCreateBase(BaseModel):
    """Fields shared by every create branch.

    ``extra="forbid"`` rejects unknown body keys at the API boundary, including
    the lifecycle fields, which no client may set.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    asset_id: UUID
    name: str = Field(min_length=1, max_length=255)


class DiscoveryScanCreate(ScanCreateBase):
    type: Literal["discovery"] = "discovery"
    config: DiscoveryConfig


class VulnerabilityScanCreate(ScanCreateBase):
    type: Literal["vulnerability"] = "vulnerability"
    config: VulnerabilityConfig


class WebScanCreate(ScanCreateBase):
    type: Literal["web"] = "web"
    config: WebConfig


class FullScanCreate(ScanCreateBase):
    type: Literal["full"] = "full"
    config: FullConfig


ScanCreateRequest = Annotated[
    DiscoveryScanCreate | VulnerabilityScanCreate | WebScanCreate | FullScanCreate,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Update: partial. Identity and lifecycle are deliberately absent.
# ---------------------------------------------------------------------------
class ScanUpdate(BaseModel):
    """Partial update payload.

    Only the mutable public fields are accepted. ``tenant_id``, ``asset_id``,
    ``status``, ``started_at`` and ``completed_at`` cannot appear here: the
    identity of a scan never changes, and its lifecycle is owned by the
    execution slices, never by an HTTP client.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    type: ScanType | None = None
    config: dict | None = None


# ---------------------------------------------------------------------------
# Response: the public whitelist.
# ---------------------------------------------------------------------------
class ScanResponse(BaseModel):
    """The public Scans response.

    Exactly eleven fields. ``from_orm_instance`` performs the explicit
    ``scan_type`` -> ``type`` mapping so the column name never reaches the wire
    and no other ORM attribute is serialised implicitly.
    """

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )

    id: UUID
    tenant_id: UUID
    asset_id: UUID
    name: str
    type: ScanType
    status: ScanStatus
    config: dict | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_instance(cls, scan: Scan) -> ScanResponse:
        """Build a :class:`ScanResponse` from an ORM :class:`Scan`."""
        data: dict[str, Any] = {
            "id": scan.id,
            "tenant_id": scan.tenant_id,
            "asset_id": scan.asset_id,
            "name": scan.name,
            "type": scan.scan_type,
            "status": scan.status,
            "config": scan.config,
            "started_at": scan.started_at,
            "completed_at": scan.completed_at,
            "created_at": scan.created_at,
            "updated_at": scan.updated_at,
        }
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# List envelope.
# ---------------------------------------------------------------------------
class ScanListResponse(BaseModel):
    """Paginated list response: items plus the page metadata."""

    items: list[ScanResponse]
    total: int
    limit: int
    offset: int
