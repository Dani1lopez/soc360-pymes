"""Pydantic schemas for the Reports domain (Slice 4 - F2).

This module is the single source of truth for the public Reports API
contract:

* :class:`ReportType`, :class:`ReportStatus` - re-exported from
  ``app.event_schemas`` so the event payloads and this module cannot drift.
* :class:`ReportCreate` - a single create schema.
* :class:`ReportUpdate` for partial PATCH.
* :class:`ReportResponse` - the response whitelist.
* :class:`ReportListResponse` - the paginated envelope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.event_schemas import ReportStatus, ReportType
from app.modules.reports.models import Report

__all__ = [
    "ReportCreate",
    "ReportListResponse",
    "ReportResponse",
    "ReportStatus",
    "ReportType",
    "ReportUpdate",
]

ReportName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]


# ---------------------------------------------------------------------------
# Create: a single shape. ``extra="forbid"`` rejects unknown body keys,
# including ``status`` and ``generated_at`` — the server always starts a
# report as "pending" with no generation timestamp.
# ---------------------------------------------------------------------------
class ReportCreate(BaseModel):
    """Create payload.

    ``status`` and ``generated_at`` are deliberately absent: the server forces
    ``status="pending"`` and ``generated_at=None`` regardless of client input.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    asset_id: UUID
    name: ReportName
    report_type: ReportType
    summary: str | None = None
    report_metadata: dict | None = None


# ---------------------------------------------------------------------------
# Update: partial. Identity fields are deliberately absent.
# ---------------------------------------------------------------------------
class ReportUpdate(BaseModel):
    """Partial update payload.

    Only ``name``, ``status``, ``summary``, ``report_metadata`` and
    ``generated_at`` are accepted. ``tenant_id``, ``asset_id`` and
    ``report_type`` identify the report and never change once recorded.
    ``name`` and ``status`` are NOT NULL columns, so an explicit ``null`` is
    rejected with 422 instead of reaching the database.
    """

    model_config = ConfigDict(extra="forbid")

    name: ReportName | None = None
    status: ReportStatus | None = None
    summary: str | None = None
    report_metadata: dict | None = None
    generated_at: datetime | None = None

    @field_validator("name", "status")
    @classmethod
    def reject_null(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("field cannot be null")
        return value


# ---------------------------------------------------------------------------
# Response: the public whitelist.
# ---------------------------------------------------------------------------
class ReportResponse(BaseModel):
    """The public Reports response."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )

    id: UUID
    tenant_id: UUID
    asset_id: UUID
    name: str
    report_type: ReportType
    status: ReportStatus
    summary: str | None
    report_metadata: dict | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_instance(cls, report: Report) -> ReportResponse:
        """Build a :class:`ReportResponse` from an ORM :class:`Report`."""
        data: dict[str, Any] = {
            "id": report.id,
            "tenant_id": report.tenant_id,
            "asset_id": report.asset_id,
            "name": report.name,
            "report_type": report.report_type,
            "status": report.status,
            "summary": report.summary,
            "report_metadata": report.report_metadata,
            "generated_at": report.generated_at,
            "created_at": report.created_at,
            "updated_at": report.updated_at,
        }
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# List envelope.
# ---------------------------------------------------------------------------
class ReportListResponse(BaseModel):
    """Paginated list response: items plus the page metadata."""

    items: list[ReportResponse]
    total: int
    limit: int
    offset: int
