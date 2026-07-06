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

    def test_db_statement_timeout_ms_default(self):
        """DB_STATEMENT_TIMEOUT_MS MUST default to 30000 (30s) for safety."""
        from app.core.config import Settings

        s = Settings()
        assert s.DB_STATEMENT_TIMEOUT_MS == 30_000

    def test_db_statement_timeout_ms_env_override(self, monkeypatch: pytest.MonkeyPatch):
        """DB_STATEMENT_TIMEOUT_MS MUST be overridable via environment variable."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "15000")
        s = Settings()
        assert s.DB_STATEMENT_TIMEOUT_MS == 15_000

    def test_db_lock_timeout_ms_default(self):
        """DB_LOCK_TIMEOUT_MS MUST default to 5000 (5s) for safety."""
        from app.core.config import Settings

        s = Settings()
        assert s.DB_LOCK_TIMEOUT_MS == 5_000

    def test_db_lock_timeout_ms_env_override(self, monkeypatch: pytest.MonkeyPatch):
        """DB_LOCK_TIMEOUT_MS MUST be overridable via environment variable."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_LOCK_TIMEOUT_MS", "10000")
        s = Settings()
        assert s.DB_LOCK_TIMEOUT_MS == 10_000

    def test_db_statement_timeout_ms_zero_rejected(self, monkeypatch: pytest.MonkeyPatch):
        """DB_STATEMENT_TIMEOUT_MS=0 MUST be rejected — PostgreSQL treats 0 as
        'disabled', which silently defeats the safety net."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "0")
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings()

    def test_db_statement_timeout_ms_negative_rejected(self, monkeypatch: pytest.MonkeyPatch):
        """DB_STATEMENT_TIMEOUT_MS with a negative value MUST be rejected."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "-5000")
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings()

    def test_db_lock_timeout_ms_zero_rejected(self, monkeypatch: pytest.MonkeyPatch):
        """DB_LOCK_TIMEOUT_MS=0 MUST be rejected — PostgreSQL treats 0 as
        'disabled', which silently defeats the safety net."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_LOCK_TIMEOUT_MS", "0")
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings()

    def test_db_lock_timeout_ms_negative_rejected(self, monkeypatch: pytest.MonkeyPatch):
        """DB_LOCK_TIMEOUT_MS with a negative value MUST be rejected."""
        from app.core.config import Settings

        monkeypatch.setenv("DB_LOCK_TIMEOUT_MS", "-1")
        with pytest.raises(Exception):  # pydantic ValidationError
            Settings()
