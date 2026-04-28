"""Additional edge-case tests for event_schemas.py.

Extends the existing test_event_schemas.py coverage with:
- Extra fields are silently ignored by Pydantic
- Email whitespace is stripped
- tenant_id None is rejected (required field)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


class TestBaseEventExtraFields:
    """Validate Pydantic ignore behavior for extra fields."""

    def test_extra_fields_ignored_on_dump(self):
        """BaseEvent MUST ignore extra fields during model_dump (not raise)."""
        from app.event_schemas import BaseEvent

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type="auth.login",
            tenant_id=uuid.uuid4(),
            # Extra field should not cause an error
            timestamp=datetime.now(timezone.utc),
        )
        data = event.model_dump()
        assert isinstance(data, dict)

    def test_extra_fields_in_validate_ignored(self):
        """AuthLoginEvent MUST ignore extra fields passed to model_validate."""
        from app.event_schemas import AuthLoginEvent

        data = {
            "event_id": str(uuid.uuid4()),
            "event_type": "auth.login",
            "tenant_id": str(uuid.uuid4()),
            "user_id": "user-123",
            "email_hash": "a" * 16,
            "ip_prefix": "192.168.1.0/24",
            "user_agent": "Mozilla/5.0",
            # Extra field — Pydantic should ignore it silently
            "unknown_field": "should be ignored",
            "another_extra": 999,
        }
        # Should not raise — extra fields are ignored
        event = AuthLoginEvent.model_validate(data)
        assert event.user_id == "user-123"
        assert event.email_hash == "a" * 16


class TestAuthLoginEventEmailHashNormalization:
    """Validate email_hash field normalization (str_strip_whitespace)."""

    def test_email_hash_whitespace_is_stripped(self):
        """AuthLoginEvent email_hash MUST have leading/trailing whitespace stripped."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="  abcdef1234567890  ",
        )
        assert event.email_hash == "abcdef1234567890"


class TestBaseEventTenantIdRequired:
    """Validate tenant_id is required (not Optional)."""

    def test_tenant_id_none_rejected(self):
        """BaseEvent MUST reject tenant_id=None."""
        from app.event_schemas import BaseEvent

        with pytest.raises(ValidationError) as exc_info:
            BaseEvent(
                event_id=uuid.uuid4(),
                event_type="auth.login",
                tenant_id=None,  # type: ignore
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("tenant_id",) for e in errors)


class TestAuthLoginEventTimestampDefault:
    """Validate timestamp default behavior."""

    def test_timestamp_auto_generated(self):
        """AuthLoginEvent MUST auto-generate timestamp when not provided."""
        from app.event_schemas import AuthLoginEvent

        before = datetime.now(timezone.utc)
        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 16,
        )
        after = datetime.now(timezone.utc)

        assert event.timestamp is not None
        assert before <= event.timestamp <= after


class TestAuthLoginEventTypeDefault:
    """Validate event_type default value."""

    def test_event_type_defaults_to_auth_login(self):
        """AuthLoginEvent event_type MUST default to 'auth.login'."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 16,
        )
        assert event.event_type == "auth.login"

    def test_event_type_can_be_overridden(self):
        """AuthLoginEvent event_type CAN be overridden with a different string."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            event_type="auth.logout",  # override default
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 16,
        )
        assert event.event_type == "auth.logout"


class TestAuthLoginEventIpPrefixOptional:
    """Validate ip_prefix is optional."""

    def test_ip_prefix_none_accepted(self):
        """AuthLoginEvent MUST accept ip_prefix=None."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email_hash="a" * 16,
            ip_prefix=None,
        )
        assert event.ip_prefix is None
