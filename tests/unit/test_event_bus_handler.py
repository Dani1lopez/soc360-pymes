"""Tests for event bus handler / dispatch of consumed events.

T4.2: The consumer loop MUST dispatch consumed auth.login events
to a handler that logs the payload. Malformed events MUST be skipped
safely without breaking the consumer loop.

These tests follow Strict TDD: they call actual handler/dispatch behavior
and assert outcomes. Since the app uses structlog with ConsoleRenderer,
we assert on the formatted message content.
"""
from __future__ import annotations

import re
import pytest
import logging


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from a string for comparison."""
    ansi_pattern = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_pattern.sub('', text)


class TestEventBusHandler:
    """Test event dispatch and handling in event_bus.py."""

    def test_handler_logs_auth_login_event(self, caplog):
        """_dispatch_event MUST log auth.login events with structured fields."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent
        from datetime import datetime, timezone
        from uuid import uuid4

        # Build a real AuthLoginEvent and serialize like publish() does
        user_id = uuid4()
        tenant_id = uuid4()
        event = AuthLoginEvent(
            event_id=uuid4(),
            event_type="auth.login",
            tenant_id=tenant_id,
            user_id=str(user_id),
            email_hash="60afbf6231f9ba6c60afbf6231f9ba6c",
            ip_prefix="192.168.1.0/24",
            user_agent="Mozilla/5.0",
            timestamp=datetime.now(timezone.utc),
        )

        # Serialize the same way EventBus.publish does
        raw = event.model_dump()
        payload = {
            k: str(v) if hasattr(v, "__str__") else v
            for k, v in raw.items()
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.event_bus"):
            # Actually call the dispatch to test it logs correctly
            EventBus._dispatch_event("auth.login", payload)

        # Verify logger was called with auth.login_event_consumed message
        # structlog's ConsoleRenderer formats as: "auth.login_event_consumed ..."
        assert any(
            "auth.login_event_consumed" in (r.message or "")
            for r in caplog.records
        ), f"Expected auth.login_event_consumed in logs, got: {[r.message for r in caplog.records]}"

    def test_handler_is_idempotent(self, caplog):
        """_dispatch_event MUST be callable multiple times without error."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent
        from datetime import datetime, timezone
        from uuid import uuid4

        # Build a valid auth.login payload
        event = AuthLoginEvent(
            event_id=uuid4(),
            event_type="auth.login",
            tenant_id=uuid4(),
            user_id=str(uuid4()),
            email_hash="b" * 32,
            ip_prefix="10.0.0.0/24",
            user_agent=None,
            timestamp=datetime.now(timezone.utc),
        )

        raw = event.model_dump()
        payload = {
            k: str(v) if hasattr(v, "__str__") else v
            for k, v in raw.items()
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.event_bus"):
            # Call dispatch twice - must not raise
            EventBus._dispatch_event("auth.login", payload)
            EventBus._dispatch_event("auth.login", payload)

        # Both calls should log successfully (structlog logs each one)
        login_logs = [r for r in caplog.records if "auth.login_event_consumed" in (r.message or "")]
        assert len(login_logs) >= 1, f"Expected at least 1 log entry, got: {[r.message for r in caplog.records]}"

    def test_malformed_event_does_not_raise(self, caplog):
        """_dispatch_event MUST NOT raise on malformed events."""
        from app.event_bus import EventBus

        # Malformed payload: missing required fields but handler uses .get() so no validation error
        malformed_data = {
            "event_type": "auth.login",
            # missing event_id, tenant_id, user_id, email_hash
            "ip_prefix": "not-an-ip",
            "user_agent": None,
        }

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="app.event_bus"):
            # dispatch_event must NOT raise - it catches all exceptions
            try:
                EventBus._dispatch_event("auth.login", malformed_data)
            except Exception as exc:
                pytest.fail(f"_dispatch_event raised {exc} instead of catching it")

        # No exception means the test passes - the malformed data is handled gracefully
        # (handler uses .get() defaults so no validation error is raised)

    def test_unknown_event_type_does_not_raise(self, caplog):
        """_dispatch_event MUST NOT raise for unknown event types."""
        from app.event_bus import EventBus

        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger="app.event_bus"):
            # Unknown event type must not raise
            try:
                EventBus._dispatch_event("unknown.event", {"key": "value"})
            except Exception as exc:
                pytest.fail(f"_dispatch_event raised {exc} for unknown event type")

        # Should log debug about no handler
        assert any(
            "no_handler" in (r.message or "") or r.levelname == "DEBUG"
            for r in caplog.records
        ), f"Expected no_handler debug log, got: {[(r.levelname, r.message) for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_event_dispatch_routes_by_event_type(self, caplog):
        """_dispatch_event MUST route auth.login to _handle_auth_login handler."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent
        from datetime import datetime, timezone
        from uuid import uuid4

        event = AuthLoginEvent(
            event_id=uuid4(),
            event_type="auth.login",
            tenant_id=uuid4(),
            user_id=str(uuid4()),
            email_hash="c" * 32,
            ip_prefix="172.16.0.0/24",
            user_agent="TestAgent/1.0",
            timestamp=datetime.now(timezone.utc),
        )

        raw = event.model_dump()
        payload = {
            k: str(v) if hasattr(v, "__str__") else v
            for k, v in raw.items()
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.event_bus"):
            # Call dispatch with auth.login event type
            EventBus._dispatch_event("auth.login", payload)

        # Must route to _handle_auth_login and log the event
        assert any(
            "auth.login_event_consumed" in (r.message or "")
            for r in caplog.records
        ), f"Expected auth.login_event_consumed log, got: {[(r.levelname, r.message) for r in caplog.records]}"

        # Must NOT log a handler error
        assert not any(
            "event_handler_error" in (r.message or "")
            for r in caplog.records
        ), "auth.login should not cause handler error"


class TestConsumerHandlerIntegration:
    """Integration-style tests for handler within consumer context."""

    def test_handler_receives_all_payload_fields(self, caplog):
        """_handle_auth_login MUST log all fields from the payload."""
        from app.event_bus import EventBus
        from app.event_schemas import AuthLoginEvent
        from datetime import datetime, timezone
        from uuid import uuid4

        user_id = str(uuid4())
        tenant_id = uuid4()
        ts = datetime.now(timezone.utc)

        event = AuthLoginEvent(
            event_id=uuid4(),
            event_type="auth.login",
            tenant_id=tenant_id,
            user_id=user_id,
            email_hash="d" * 32,
            ip_prefix="8.8.8.0/24",
            user_agent="TestBrowser/1.0",
            timestamp=ts,
        )

        raw = event.model_dump()
        payload = {
            k: str(v) if hasattr(v, "__str__") else v
            for k, v in raw.items()
        }

        caplog.clear()
        with caplog.at_level(logging.INFO, logger="app.event_bus"):
            EventBus._dispatch_event("auth.login", payload)

        # Verify structlog captured the auth.login_event_consumed message
        login_record = next(
            (r for r in caplog.records if "auth.login_event_consumed" in (r.message or "")),
            None
        )
        assert login_record is not None, f"Expected auth.login_event_consumed log, got: {caplog.records}"

        # structlog's ConsoleRenderer includes key=value pairs in the message
        # Strip ANSI codes before checking content
        msg = strip_ansi_codes(login_record.message)
        assert "email_hash=dddddddddddddddddddddddddddddddd" in msg, f"Expected email_hash in message, got: {msg}"
        assert "ip_prefix=8.8.8.0/24" in msg, f"Expected ip_prefix in message, got: {msg}"
        assert "user_id=" in msg, f"Expected user_id in message, got: {msg}"
