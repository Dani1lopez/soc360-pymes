"""Tests for structured Redis configuration and REDIS_URL rejection (PR1).

Verifies:
- REDIS_URL is rejected whenever present (env or kwargs).
- Structured REDIS_HOST/PORT/DB/PASSWORD:SecretStr is the only valid path.
- REDIS_PASSWORD is a SecretStr (never leaked in repr/str).
- Production requires a non-empty REDIS_PASSWORD.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

# Shared required fields (no REDIS_URL — structured fields only)
_REQUIRED = dict(
    ENVIRONMENT="development",
    DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
    DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
    POSTGRES_USER="test",
    POSTGRES_PASSWORD="test",
    POSTGRES_DB="test",
    LLM_PROVIDER="ollama",
)


class TestRedisUrlRejected:
    """REDIS_URL must be rejected whenever it is present."""

    def test_redis_url_rejected_when_set(self, monkeypatch: pytest.MonkeyPatch):
        """REDIS_URL in the environment must raise a clear validation error."""
        from app.core.config import Settings

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        with pytest.raises(ValidationError, match="REDIS_URL"):
            Settings(_env_file=None, **_REQUIRED)

    def test_redis_url_rejected_when_present_but_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Presence, rather than truthiness, selects the rejected legacy path."""
        from app.core.config import Settings

        monkeypatch.setenv("REDIS_URL", "")
        with pytest.raises(ValidationError, match="REDIS_URL"):
            Settings(_env_file=None, **_REQUIRED)

    def test_redis_url_rejected_from_kwargs(self):
        """REDIS_URL passed as a kwarg must raise a clear validation error."""
        from app.core.config import Settings

        with pytest.raises((ValidationError, ValueError), match="REDIS_URL"):
            Settings(
                _env_file=None,
                REDIS_URL="redis://localhost:6379/0",
                **_REQUIRED,
            )

    def test_redis_url_rejected_from_dotenv_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        """REDIS_URL supplied only by a dotenv file must be rejected."""
        from app.core.config import Settings

        monkeypatch.delenv("REDIS_URL", raising=False)
        env_file = tmp_path / "redis-url.env"
        env_file.write_text(
            "\n".join(
                [
                    "ENVIRONMENT=development",
                    "DATABASE_URL=postgresql+asyncpg://test:test@localhost/test",
                    "DATABASE_URL_MIGRATION=postgresql+asyncpg://test:test@localhost/test",
                    "POSTGRES_USER=test",
                    "POSTGRES_PASSWORD=test",
                    "POSTGRES_DB=test",
                    "LLM_PROVIDER=ollama",
                    "REDIS_URL=redis://localhost:6379/0",
                ]
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValidationError, match="REDIS_URL"):
            Settings(_env_file=env_file)


class TestStructuredRedisSettings:
    """Structured REDIS_HOST/PORT/DB/PASSWORD must be the only valid path."""

    def test_structured_redis_settings_accepted(self):
        """Valid structured settings must be accepted without error."""
        from app.core.config import Settings

        s = Settings(
            _env_file=None,
            REDIS_HOST="redis.example.com",
            REDIS_PORT=6380,
            REDIS_DB=3,
            REDIS_PASSWORD="s3cret",
            **_REQUIRED,
        )
        assert s.REDIS_HOST == "redis.example.com"
        assert s.REDIS_PORT == 6380
        assert s.REDIS_DB == 3
        assert isinstance(s.REDIS_PASSWORD, SecretStr)
        assert s.REDIS_PASSWORD.get_secret_value() == "s3cret"

    def test_redis_password_is_secret_str(self):
        """REDIS_PASSWORD must be a SecretStr — never leaked in repr."""
        from app.core.config import Settings

        s = Settings(
            _env_file=None,
            REDIS_PASSWORD="my_secret_pass",
            **_REQUIRED,
        )
        assert isinstance(s.REDIS_PASSWORD, SecretStr)
        # repr must NOT contain the actual password
        assert "my_secret_pass" not in repr(s.REDIS_PASSWORD)

    def test_redis_defaults(self, monkeypatch: pytest.MonkeyPatch):
        """REDIS_HOST/PORT/DB must have sensible defaults when not overridden."""
        from app.core.config import Settings

        # Clear any env vars that would override defaults
        for key in ("REDIS_HOST", "REDIS_PORT", "REDIS_DB"):
            monkeypatch.delenv(key, raising=False)

        s = Settings(
            _env_file=None,
            REDIS_PASSWORD="test_pass",
            **_REQUIRED,
        )
        assert s.REDIS_HOST == "localhost"
        assert s.REDIS_PORT == 6379
        assert s.REDIS_DB == 0

    def test_production_requires_non_empty_password(self):
        """Production environment must reject empty REDIS_PASSWORD."""
        from app.core.config import Settings

        prod_required = {**_REQUIRED, "ENVIRONMENT": "production"}
        with pytest.raises(ValidationError, match="REDIS_PASSWORD"):
            Settings(
                _env_file=None,
                REDIS_PASSWORD="",
                **prod_required,
            )

    def test_settings_do_not_expose_legacy_redis_url_accessor(self):
        """The rejected URL must not remain as a compatibility accessor."""
        from app.core.config import Settings

        settings = Settings(_env_file=None, REDIS_PASSWORD="test_pass", **_REQUIRED)
        assert not hasattr(settings, "REDIS_URL")


def test_get_pool_uses_authenticated_structured_settings(monkeypatch: pytest.MonkeyPatch):
    """Pool construction passes structured fields and the secret to redis-py."""
    import app.core.redis as redis_module
    from app.core.redis import close_pool, get_pool

    class RedisSettings:
        REDIS_HOST = "redis.example.com"
        REDIS_PORT = 6380
        REDIS_DB = 4
        REDIS_PASSWORD = SecretStr("pool-secret")
        REDIS_MAX_CONNECTIONS = 7

    monkeypatch.setattr(redis_module, "settings", RedisSettings())
    monkeypatch.setattr(redis_module, "_pool", None)
    pool = get_pool()
    assert pool.connection_kwargs["host"] == "redis.example.com"
    assert pool.connection_kwargs["port"] == 6380
    assert pool.connection_kwargs["db"] == 4
    assert pool.connection_kwargs["password"] == "pool-secret"
    assert pool.max_connections == 7

    # Keep the singleton isolated from the process-global test fixture.
    import asyncio

    asyncio.run(close_pool())
