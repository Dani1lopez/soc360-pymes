"""Tests for event_schemas.py (T2.1) — Pydantic models for auth.login event."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


class TestBaseEvent:
    """Validate BaseEvent Pydantic model."""

    def test_base_event_requires_event_id(self):
        """BaseEvent MUST require event_id field."""
        from app.event_schemas import BaseEvent

        with pytest.raises(ValidationError) as exc_info:
            BaseEvent(
                event_type="auth.login",
                tenant_id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("event_id",) for e in errors)

    def test_base_event_requires_event_type(self):
        """BaseEvent MUST require event_type field."""
        from app.event_schemas import BaseEvent

        with pytest.raises(ValidationError) as exc_info:
            BaseEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("event_type",) for e in errors)

    def test_base_event_requires_tenant_id(self):
        """BaseEvent MUST require tenant_id field."""
        from app.event_schemas import BaseEvent

        with pytest.raises(ValidationError) as exc_info:
            BaseEvent(
                event_id=uuid.uuid4(),
                event_type="auth.login",
                timestamp=datetime.now(timezone.utc),
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("tenant_id",) for e in errors)

    def test_base_event_timestamp_defaults_to_now(self):
        """BaseEvent timestamp MUST default to current UTC time when not provided."""
        from app.event_schemas import BaseEvent

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type="auth.login",
            tenant_id=uuid.uuid4(),
        )
        assert event.timestamp is not None
        assert isinstance(event.timestamp, datetime)
        # Should be close to now (within 5 seconds)
        delta = abs((datetime.now(timezone.utc) - event.timestamp).total_seconds())
        assert delta < 5

    def test_base_event_accepts_valid_data(self):
        """BaseEvent MUST accept all required fields with valid types."""
        from app.event_schemas import BaseEvent

        event = BaseEvent(
            event_id=uuid.uuid4(),
            event_type="auth.login",
            tenant_id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        assert event.event_type == "auth.login"
        assert isinstance(event.event_id, uuid.UUID)
        assert isinstance(event.tenant_id, uuid.UUID)

    def test_base_event_types_are_correct(self):
        """BaseEvent fields MUST have correct types: UUID, str, UUID, datetime."""
        from app.event_schemas import BaseEvent

        event_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        ts = datetime.now(timezone.utc)

        event = BaseEvent(
            event_id=event_id,
            event_type="auth.login",
            tenant_id=tenant_id,
            timestamp=ts,
        )
        assert type(event.event_id) is uuid.UUID
        assert type(event.event_type) is str
        assert type(event.tenant_id) is uuid.UUID
        assert type(event.timestamp) is datetime


class TestAuthLoginEvent:
    """Validate AuthLoginEvent Pydantic model."""

    def test_auth_login_event_requires_user_id(self):
        """AuthLoginEvent MUST require user_id field."""
        from app.event_schemas import AuthLoginEvent

        with pytest.raises(ValidationError) as exc_info:
            AuthLoginEvent(
                user_id="",  # empty string should fail
                email="user@example.com",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("user_id",) for e in errors)

    def test_auth_login_event_requires_email(self):
        """AuthLoginEvent MUST require email field."""
        from app.event_schemas import AuthLoginEvent

        with pytest.raises(ValidationError) as exc_info:
            AuthLoginEvent(
                user_id="user-123",
                email="",  # empty should fail
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("email",) for e in errors)

    def test_auth_login_event_email_must_be_valid(self):
        """AuthLoginEvent email MUST be a valid email format."""
        from app.event_schemas import AuthLoginEvent

        with pytest.raises(ValidationError) as exc_info:
            AuthLoginEvent(
                user_id="user-123",
                email="not-an-email",
                ip_address="192.168.1.1",
                user_agent="Mozilla/5.0",
            )
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("email",) for e in errors)

    def test_auth_login_event_optional_fields_default_to_none(self):
        """AuthLoginEvent ip_address and user_agent MUST default to None when not provided."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email="user@example.com",
        )
        assert event.ip_address is None
        assert event.user_agent is None

    def test_auth_login_event_accepts_full_data(self):
        """AuthLoginEvent MUST accept all fields with valid data."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email="user@example.com",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        assert event.user_id == "user-123"
        assert event.email == "user@example.com"
        assert event.ip_address == "192.168.1.1"
        assert event.user_agent == "Mozilla/5.0"

    def test_auth_login_event_inherits_from_base(self):
        """AuthLoginEvent MUST inherit event_id, tenant_id, timestamp from BaseEvent."""
        from app.event_schemas import AuthLoginEvent

        event_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        ts = datetime.now(timezone.utc)

        event = AuthLoginEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            timestamp=ts,
            user_id="user-123",
            email="user@example.com",
        )
        assert event.event_id == event_id
        assert event.tenant_id == tenant_id
        assert event.timestamp == ts


class TestAuthLoginEventSerialization:
    """Validate serialization/deserialization of AuthLoginEvent."""

    def test_model_dump_returns_dict(self):
        """model_dump() MUST return a plain dict with all fields."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email="user@example.com",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        data = event.model_dump()
        assert isinstance(data, dict)
        assert data["user_id"] == "user-123"
        assert data["email"] == "user@example.com"
        assert data["ip_address"] == "192.168.1.1"
        assert data["user_agent"] == "Mozilla/5.0"
        assert "event_id" in data
        assert "tenant_id" in data
        assert "timestamp" in data

    def test_model_dump_json_returns_json_string(self):
        """model_dump_json() MUST return a valid JSON string."""
        from app.event_schemas import AuthLoginEvent

        event = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email="user@example.com",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        json_str = event.model_dump_json()
        assert isinstance(json_str, str)
        assert "user-123" in json_str
        assert "user@example.com" in json_str

    def test_model_validate_round_trip(self):
        """model_validate() MUST reconstruct an identical event."""
        from app.event_schemas import AuthLoginEvent

        original = AuthLoginEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            user_id="user-123",
            email="user@example.com",
            ip_address="192.168.1.1",
            user_agent="Mozilla/5.0",
        )
        data = original.model_dump()
        restored = AuthLoginEvent.model_validate(data)
        assert restored.user_id == original.user_id
        assert restored.email == original.email
        assert restored.ip_address == original.ip_address
        assert restored.user_agent == original.user_agent
        assert restored.event_id == original.event_id
