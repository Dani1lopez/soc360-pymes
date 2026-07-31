"""Configuration tests for distributed-lock settings."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

_REQUIRED = dict(
    DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
    DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
    POSTGRES_USER="test",
    POSTGRES_PASSWORD="test",
    POSTGRES_DB="test",
    SECRET_KEY="".join(chr(ord("a") + i % 26) for i in range(128)),
    LLM_PROVIDER="ollama",
)


def _make_settings(**overrides):
    from app.core.config import Settings

    values = {"_env_file": None, "ENVIRONMENT": "development", **_REQUIRED}
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("secret, message", [("", "LOCK_KEY_SECRET"), ("a" * 31, "32")])
def test_production_lock_secret_is_required(secret: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _make_settings(
            ENVIRONMENT="production",
            REDIS_PASSWORD="redis-password",
            METRICS_TOKEN="metrics-token",
            LOCK_KEY_SECRET=secret,
        )


def test_development_defaults_and_minimum_are_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCK_MIN_TTL_SECONDS", "30")
    settings = _make_settings(LOCK_KEY_SECRET="")
    assert isinstance(settings.LOCK_KEY_SECRET, SecretStr)
    assert settings.LOCK_KEY_SECRET.get_secret_value() == ""
    assert (
        settings.LOCK_DEFAULT_TTL_SECONDS,
        settings.LOCK_DEFAULT_RETRY_AFTER_SECONDS,
    ) == (30, 15)
    assert (
        settings.LOCK_RETRY_AFTER_SECONDS is None and settings.LOCK_MIN_TTL_SECONDS == 1
    )


@pytest.mark.parametrize(
    "value, valid",
    [
        (1, True),
        (15, True),
        (300, True),
        (0, False),
        (301, False),
        (-1, False),
        ("not-an-int", False),
    ],
)
def test_lock_retry_after_override_range(value, valid: bool) -> None:
    if valid:
        assert (
            _make_settings(LOCK_RETRY_AFTER_SECONDS=value).LOCK_RETRY_AFTER_SECONDS
            == value
        )
    else:
        with pytest.raises(
            (ValidationError, ValueError), match="LOCK_RETRY_AFTER_SECONDS"
        ):
            _make_settings(LOCK_RETRY_AFTER_SECONDS=value)
