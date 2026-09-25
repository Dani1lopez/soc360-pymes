"""Event schemas for Redis Streams event bus.

Defines Pydantic models for typed event contracts.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

# RFC 5322 simplified regex - validates email format without TLD restrictions
_EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _validate_email_with_test_domain(value: str | bytes) -> str:
    """Validate email format, allowing '.test' reserved TLD for seed/test data.

    Pydantic 2's built-in EmailStr rejects '.test' domains (reserved for testing),
    but our seed data uses addresses like admin@alpha.test.
    """
    if isinstance(value, bytes):
        value = value.decode()
    # Strip whitespace - the model's str_strip_whitespace handles this too,
    # but we need to validate the stripped version
    value = value.strip()
    if value.endswith(".test"):
        # Allow .test reserved TLD for test/seed data
        return value
    # Validate normal email format
    if not _EMAIL_REGEX.match(value):
        raise ValueError(f"Invalid email format: {value}")
    return value


EmailStrTestable = Annotated[str, BeforeValidator(_validate_email_with_test_domain)]


class BaseEvent(BaseModel):
    """Base event envelope with common fields.

    All events published to the bus MUST inherit from this class
    to ensure a consistent contract: event_id, event_type, tenant_id, timestamp.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_id: Annotated[uuid.UUID, Field(description="Unique event identifier (UUID)")]
    event_type: Annotated[
        str, Field(description="Dot-namespaced event type, e.g. auth.login")
    ]
    tenant_id: Annotated[uuid.UUID, Field(description="Tenant that owns this event")]
    timestamp: Annotated[
        datetime,
        Field(
            default_factory=lambda: datetime.now(UTC),
            description="UTC timestamp of event emission",
        ),
    ]


class AuthLoginEvent(BaseEvent):
    """auth.login event emitted after a successful login.

    Emitted by: app/modules/auth/service.py
    Consumed by: consumer groups listening on events:auth.login
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Annotated[
        str, Field(default="auth.login", description="Event type discriminator")
    ]
    user_id: Annotated[str, Field(min_length=1, description="Authenticated user ID")]
    email_hash: Annotated[
        str, Field(min_length=1, description="SHA256[:32] of user email")
    ]
    ip_prefix: Annotated[
        str | None,
        Field(default=None, description="Masked IP /24 prefix, e.g. 192.168.1.0/24"),
    ]
    user_agent: Annotated[
        str | None, Field(default=None, description="Client User-Agent if available")
    ]


class TenantlessEvent(BaseEvent):
    """Event base for system-level events without a tenant scope.

    Allows `tenant_id` to be absent or `None` for system-level audit events.
    `BaseEvent` remains unchanged — existing tenant-scoped events continue
    to require a UUID tenant id.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    tenant_id: Annotated[
        uuid.UUID | None,
        Field(
            default=None,
            description="Tenant that owns this event (None for system events)",
        ),
    ]


class AuthSuperadminLoginEvent(TenantlessEvent):
    """system.auth.login event emitted after a superadmin login.

    Tenantless — superadmins operate outside any tenant scope.
    `is_superadmin=True` is explicit so consumers don't need to parse
    stream names to infer event semantics.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Annotated[
        str, Field(default="system.auth.login", description="Event type discriminator")
    ]
    user_id: Annotated[str, Field(min_length=1, description="Authenticated user ID")]
    email_hash: Annotated[
        str, Field(min_length=1, description="SHA256[:32] of user email")
    ]
    ip_prefix: Annotated[
        str | None,
        Field(default=None, description="Masked IP /24 prefix, e.g. 192.168.1.0/24"),
    ]
    user_agent: Annotated[
        str | None, Field(default=None, description="Client User-Agent if available")
    ]
    is_superadmin: Annotated[
        bool,
        Field(default=True, description="Flag indicating superadmin authentication"),
    ]


# ---------------------------------------------------------------------------
# F2 — Assets domain events (Slice 1)
# ---------------------------------------------------------------------------

# AssetType — the six canonical asset_type values used by the Assets domain.
# This Literal lives here so every event payload references the same source
# of truth without coupling to app/modules/assets/schemas.py.
AssetType = Literal[
    "ip",
    "domain",
    "hostname",
    "web_app",
    "subnet",
    "cloud_resource",
]


# ScanType — the four canonical scan types used by the Scans domain. Like
# AssetType, it lives here so every event payload references the same source
# of truth without coupling to app/modules/scans/schemas.py.
ScanType = Literal[
    "discovery",
    "vulnerability",
    "web",
    "full",
]

ScanStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


class AssetCreatedEvent(BaseEvent):
    """asset.created event emitted after a successful POST /assets.

    Consumed by: any slice that wants to mirror asset creation (search index,
    detection pipeline, dashboards). Payload shape:
        {event_id, event_type, timestamp, asset_id, tenant_id, type, value, created_at}
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["asset.created"] = "asset.created"
    asset_id: uuid.UUID
    type: AssetType
    value: str
    created_at: datetime


class AssetUpdatedEvent(BaseEvent):
    """asset.updated event emitted after a successful PATCH /assets/{id}.

    ``changed_fields`` is the ordered list of public field names that actually
    changed in this mutation (e.g. ``["value"]`` or ``["type", "value"]``).
    Consumers must NOT infer change sets from comparing snapshots.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["asset.updated"] = "asset.updated"
    asset_id: uuid.UUID
    changed_fields: list[str]


class AssetDeletedEvent(BaseEvent):
    """asset.deleted event emitted after a successful DELETE /assets/{id}."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["asset.deleted"] = "asset.deleted"
    asset_id: uuid.UUID


# ---------------------------------------------------------------------------
# F2 — Scans domain events (Slice 2)
# ---------------------------------------------------------------------------


class ScanCreatedEvent(BaseEvent):
    """scan.created event emitted after a successful POST /scans.

    Emitted by: app/modules/scans/service.py, only after the commit succeeds.
    Consumed by: slices that react to a new scan definition being persisted
    (execution scheduling, dashboards). Payload shape:
        {event_id, event_type, timestamp, scan_id, tenant_id, asset_id, name,
         type, status, config, created_at}
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["scan.created"] = "scan.created"
    scan_id: uuid.UUID
    asset_id: uuid.UUID
    name: str
    type: ScanType
    status: ScanStatus
    config: dict | None
    created_at: datetime


class ScanUpdatedEvent(BaseEvent):
    """scan.updated event emitted after a successful PATCH /scans/{id}.

    ``changed_fields`` is the ordered list of public field names that actually
    changed in this mutation (e.g. ``["name"]`` or ``["type", "config"]``).
    Consumers must NOT infer change sets from comparing snapshots.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["scan.updated"] = "scan.updated"
    scan_id: uuid.UUID
    changed_fields: list[str]


class ScanDeletedEvent(BaseEvent):
    """scan.deleted event emitted after a successful DELETE /scans/{id}."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["scan.deleted"] = "scan.deleted"
    scan_id: uuid.UUID


# ---------------------------------------------------------------------------
# F2 — Vulnerabilities domain events (Slice 3)
# ---------------------------------------------------------------------------

# VulnerabilitySeverity — the five canonical severity values used by the
# Vulnerabilities domain. Like ScanType, it lives here so every event payload
# references the same source of truth without coupling to
# app/modules/vulnerabilities/schemas.py.
VulnerabilitySeverity = Literal["critical", "high", "medium", "low", "info"]

VulnerabilityStatus = Literal["open", "fixed", "accepted_risk", "false_positive"]


class VulnerabilityCreatedEvent(BaseEvent):
    """vulnerability.created event emitted after a successful POST /vulnerabilities.

    Emitted by: app/modules/vulnerabilities/service.py, only after the commit
    succeeds. Consumed by: slices that react to a new vulnerability being
    persisted (dashboards, reports). Payload shape:
        {event_id, event_type, timestamp, vulnerability_id, tenant_id, scan_id,
         title, severity, status, cve_id, cvss_score, created_at}
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["vulnerability.created"] = "vulnerability.created"
    vulnerability_id: uuid.UUID
    scan_id: uuid.UUID
    title: str
    severity: VulnerabilitySeverity
    status: VulnerabilityStatus
    cve_id: str | None
    cvss_score: float | None
    created_at: datetime


class VulnerabilityUpdatedEvent(BaseEvent):
    """vulnerability.updated event emitted after a successful PATCH /vulnerabilities/{id}.

    ``changed_fields`` is the ordered list of public field names that actually
    changed in this mutation (e.g. ``["status"]`` or ``["status", "description"]``).
    Consumers must NOT infer change sets from comparing snapshots.
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["vulnerability.updated"] = "vulnerability.updated"
    vulnerability_id: uuid.UUID
    changed_fields: list[str]


class VulnerabilityDeletedEvent(BaseEvent):
    """vulnerability.deleted event emitted after a successful DELETE /vulnerabilities/{id}."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Literal["vulnerability.deleted"] = "vulnerability.deleted"
    vulnerability_id: uuid.UUID
