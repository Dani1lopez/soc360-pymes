"""Tests for Redis Streams event bus configuration (T1.1)."""
from __future__ import annotations



class TestEventBusConfig:
    """Test that Redis Streams event bus settings are present in Settings."""

    def test_event_bus_settings_fields_exist(self):
        """Settings MUST have event bus stream prefix, consumer group, and retry fields."""
        from app.core.config import settings

        assert hasattr(settings, "EVENT_STREAM_PREFIX"), "EVENT_STREAM_PREFIX is missing"
        assert hasattr(settings, "EVENT_CONSUMER_GROUP"), "EVENT_CONSUMER_GROUP is missing"
        assert hasattr(settings, "EVENT_MAX_RETRIES"), "EVENT_MAX_RETRIES is missing"
        assert hasattr(settings, "EVENT_STREAM_MAXLEN"), "EVENT_STREAM_MAXLEN is missing"
        assert hasattr(settings, "EVENT_STREAM_MAXAGE_SECONDS"), "EVENT_STREAM_MAXAGE_SECONDS is missing"

    def test_event_bus_settings_defaults(self):
        """Event bus settings MUST have sensible defaults from spec."""
        from app.core.config import settings

        # stream prefix: distinct from auth-state keys (revoked:*, active_jtis:*)
        assert settings.EVENT_STREAM_PREFIX == "events"
        # consumer group for exactly-once delivery
        assert settings.EVENT_CONSUMER_GROUP == "soc360-consumers"
        # retry exhaustion limit
        assert settings.EVENT_MAX_RETRIES == 3
        # retention: bounded stream length
        assert settings.EVENT_STREAM_MAXLEN == 100000
        # retention: TTL-based (7 days in seconds)
        assert settings.EVENT_STREAM_MAXAGE_SECONDS == 604800
