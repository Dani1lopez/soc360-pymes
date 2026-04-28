"""Tests for app/core/config.py — settings env override behavior."""
from __future__ import annotations

import os

import pytest


class TestSettingsEnvOverride:
    """Validate that Settings fields can be overridden via environment variables."""

    def test_event_max_retries_env_override(self, monkeypatch: pytest.MonkeyPatch):
        """EVENT_MAX_RETRIES MUST be overridable via environment variable."""
        from app.core.config import Settings

        monkeypatch.setenv("EVENT_MAX_RETRIES", "7")
        # Create a fresh Settings instance — the module-level `settings` singleton
        # was already loaded with defaults; we test override on a new instance.
        local_settings = Settings.model_construct()
        # Use model_validate with _env_sources_ to pick up env vars
        local_settings = Settings()
        assert local_settings.EVENT_MAX_RETRIES == 7

    def test_event_stream_prefix_env_override(self, monkeypatch: pytest.MonkeyPatch):
        """EVENT_STREAM_PREFIX MUST be overridable via environment variable."""
        from app.core.config import Settings

        monkeypatch.setenv("EVENT_STREAM_PREFIX", "custom_events")
        local_settings = Settings()
        assert local_settings.EVENT_STREAM_PREFIX == "custom_events"
