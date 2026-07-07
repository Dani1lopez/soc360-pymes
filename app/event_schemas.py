"""Event schemas for Redis Streams event bus.

Defines Pydantic models for typed event contracts.
"""
from __future__ import annotations

import uuid
import re
from datetime import datetime, timezone
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, BeforeValidator


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
    event_type: Annotated[str, Field(description="Dot-namespaced event type, e.g. auth.login")]
    tenant_id: Annotated[uuid.UUID, Field(description="Tenant that owns this event")]
    timestamp: Annotated[datetime, Field(default_factory=lambda: datetime.now(timezone.utc), description="UTC timestamp of event emission")]


class AuthLoginEvent(BaseEvent):
    """auth.login event emitted after a successful login.

    Emitted by: app/modules/auth/service.py
    Consumed by: consumer groups listening on events:auth.login
    """

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    event_type: Annotated[str, Field(default="auth.login", description="Event type discriminator")]
    user_id: Annotated[str, Field(min_length=1, description="Authenticated user ID")]
    email_hash: Annotated[str, Field(min_length=1, description="SHA256[:32] of user email")]
    ip_prefix: Annotated[str | None, Field(default=None, description="Masked IP /24 prefix, e.g. 192.168.1.0/24")]
    user_agent: Annotated[str | None, Field(default=None, description="Client User-Agent if available")]


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
        Field(default=None, description="Tenant that owns this event (None for system events)"),
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

    event_type: Annotated[str, Field(default="system.auth.login", description="Event type discriminator")]
    user_id: Annotated[str, Field(min_length=1, description="Authenticated user ID")]
    email_hash: Annotated[str, Field(min_length=1, description="SHA256[:32] of user email")]
    ip_prefix: Annotated[str | None, Field(default=None, description="Masked IP /24 prefix, e.g. 192.168.1.0/24")]
    user_agent: Annotated[str | None, Field(default=None, description="Client User-Agent if available")]
    is_superadmin: Annotated[bool, Field(default=True, description="Flag indicating superadmin authentication")]
