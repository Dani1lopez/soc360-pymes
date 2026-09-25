"""Pydantic schemas for the Vulnerabilities domain (Slice 3 - F2).

This module is the single source of truth for the public Vulnerabilities API
contract:

* :class:`VulnerabilitySeverity`, :class:`VulnerabilityStatus` - re-exported
  from ``app.event_schemas`` so the event payloads and this module cannot
  drift.
* :class:`VulnerabilityCreate` - a single create schema (no discriminated
  union: unlike Scans, a vulnerability has one shape regardless of severity).
* :class:`VulnerabilityUpdate` for partial PATCH.
* :class:`VulnerabilityResponse` - the response whitelist.
* :class:`VulnerabilityListResponse` - the paginated envelope.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.event_schemas import VulnerabilitySeverity, VulnerabilityStatus
from app.modules.vulnerabilities.models import Vulnerability

__all__ = [
    "VulnerabilityCreate",
    "VulnerabilityListResponse",
    "VulnerabilityResponse",
    "VulnerabilitySeverity",
    "VulnerabilityStatus",
    "VulnerabilityUpdate",
]


# ---------------------------------------------------------------------------
# Create: a single shape. ``extra="forbid"`` rejects unknown body keys,
# including ``status`` — the server always forces it to "open".
# ---------------------------------------------------------------------------
class VulnerabilityCreate(BaseModel):
    """Create payload.

    ``status`` is deliberately absent: the server forces it to ``"open"``
    regardless of client input, matching the Scans pattern of owning the
    lifecycle server-side.
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    scan_id: UUID
    title: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
    ]
    description: str | None = None
    severity: VulnerabilitySeverity
    cve_id: Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)] | None = None
    cvss_score: float | None = None
    vulnerability_metadata: dict | None = None


# ---------------------------------------------------------------------------
# Update: partial. Identity and finding-source fields are deliberately
# absent — only the fields a triage workflow legitimately mutates.
# ---------------------------------------------------------------------------
class VulnerabilityUpdate(BaseModel):
    """Partial update payload.

    Only ``status``, ``description``, ``cvss_score`` and
    ``vulnerability_metadata`` are accepted. ``title``, ``scan_id``,
    ``tenant_id``, ``severity`` and ``cve_id`` cannot appear here: they
    identify the finding and where it came from, and never change once
    recorded — matching Scans' pattern of keeping identity fields out of
    PATCH.
    """

    model_config = ConfigDict(extra="forbid")

    status: VulnerabilityStatus | None = None
    description: str | None = None
    cvss_score: float | None = None
    vulnerability_metadata: dict | None = None


# ---------------------------------------------------------------------------
# Response: the public whitelist.
# ---------------------------------------------------------------------------
class VulnerabilityResponse(BaseModel):
    """The public Vulnerabilities response."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        populate_by_name=True,
    )

    id: UUID
    tenant_id: UUID
    scan_id: UUID
    title: str
    description: str | None
    severity: VulnerabilitySeverity
    status: VulnerabilityStatus
    cve_id: str | None
    cvss_score: float | None
    vulnerability_metadata: dict | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_instance(cls, vulnerability: Vulnerability) -> VulnerabilityResponse:
        """Build a :class:`VulnerabilityResponse` from an ORM :class:`Vulnerability`."""
        data: dict[str, Any] = {
            "id": vulnerability.id,
            "tenant_id": vulnerability.tenant_id,
            "scan_id": vulnerability.scan_id,
            "title": vulnerability.title,
            "description": vulnerability.description,
            "severity": vulnerability.severity,
            "status": vulnerability.status,
            "cve_id": vulnerability.cve_id,
            "cvss_score": (
                float(vulnerability.cvss_score)
                if vulnerability.cvss_score is not None
                else None
            ),
            "vulnerability_metadata": vulnerability.vulnerability_metadata,
            "created_at": vulnerability.created_at,
            "updated_at": vulnerability.updated_at,
        }
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# List envelope.
# ---------------------------------------------------------------------------
class VulnerabilityListResponse(BaseModel):
    """Paginated list response: items plus the page metadata."""

    items: list[VulnerabilityResponse]
    total: int
    limit: int
    offset: int
