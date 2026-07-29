"""Tests for app/core/config.py — REDIS_OUTAGE_RETRY_AFTER_SECONDS boundary validation.

PR4 #260: must accept 1..300 inclusive and reject 0, 301, non-integers.
"""
from __future__ import annotations

import pytest


def _make_settings(**overrides):
    """Construct a ``Settings`` instance; ``_env_file=None`` isolates from operator ``.env``."""
    from app.core.config import Settings

    base = dict(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
        SECRET_KEY="".join(chr(ord("a") + (i % 26)) for i in range(128)),
        LLM_PROVIDER="ollama",
        ENVIRONMENT="development",
    )
    base.update(overrides)
    return Settings(**base)


class TestRetryAfterBoundaries:
    """``REDIS_OUTAGE_RETRY_AFTER_SECONDS`` MUST accept 1..300 and reject others."""

    @pytest.mark.parametrize("value", [0, 301, -1])
    def test_below_or_above_range_rejected(self, value: int) -> None:
        with pytest.raises(ValueError, match="(?i)REDIS_OUTAGE_RETRY_AFTER_SECONDS"):
            _make_settings(REDIS_OUTAGE_RETRY_AFTER_SECONDS=value)

    def test_non_integer_rejected(self) -> None:
        with pytest.raises(ValueError):
            _make_settings(REDIS_OUTAGE_RETRY_AFTER_SECONDS="not-an-int")  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [1, 30, 300])
    def test_in_range_accepted(self, value: int) -> None:
        s = _make_settings(REDIS_OUTAGE_RETRY_AFTER_SECONDS=value)
        assert s.REDIS_OUTAGE_RETRY_AFTER_SECONDS == value
