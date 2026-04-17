from __future__ import annotations

import os
import pytest


class TestLLMSettingsFields:
    """Verify Settings has all required LLM-related fields."""

    def test_llm_provider_field_exists(self):
        """Settings must have LLM_PROVIDER field."""
        from app.core.config import Settings

        s = Settings.model_construct(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert hasattr(s, "LLM_PROVIDER")

    def test_llm_timeout_field_exists(self):
        """Settings must have LLM_TIMEOUT field."""
        from app.core.config import Settings

        s = Settings.model_construct(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert hasattr(s, "LLM_TIMEOUT")

    def test_llm_max_tokens_field_exists(self):
        """Settings must have LLM_MAX_TOKENS field."""
        from app.core.config import Settings

        s = Settings.model_construct(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert hasattr(s, "LLM_MAX_TOKENS")

    def test_llm_temperature_field_exists(self):
        """Settings must have LLM_TEMPERATURE field."""
        from app.core.config import Settings

        s = Settings.model_construct(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert hasattr(s, "LLM_TEMPERATURE")

    def test_per_provider_key_fields_exist(self):
        """Settings must have per-provider API key fields."""
        from app.core.config import Settings

        s = Settings.model_construct(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        # All these must exist
        assert hasattr(s, "OPENAI_API_KEY")
        assert hasattr(s, "ANTHROPIC_API_KEY")
        assert hasattr(s, "GEMINI_API_KEY")
        assert hasattr(s, "MISTRAL_API_KEY")
        assert hasattr(s, "COHERE_API_KEY")
        assert hasattr(s, "TOGETHER_API_KEY")
        assert hasattr(s, "HUGGINGFACE_API_KEY")


class TestLLMProviderValidator:
    """Verify LLM_PROVIDER validator rejects invalid values."""

    def test_llm_provider_rejects_invalid_value(self):
        """LLM_PROVIDER must be validated against allowed providers."""
        from app.core.config import Settings

        # These required fields must be present even if we're testing the validator
        with pytest.raises(ValueError, match="LLM_PROVIDER"):
            Settings(
                SECRET_KEY="x" * 32,
                DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
                DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
                POSTGRES_USER="test",
                POSTGRES_PASSWORD="test",
                POSTGRES_DB="test",
                GROQ_API_KEY="gsk_test_key",
                LLM_PROVIDER="invalid_provider",
            )

    def test_llm_provider_accepts_valid_value_groq(self):
        """LLM_PROVIDER must accept 'groq'."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
            LLM_PROVIDER="groq",
        )
        assert s.LLM_PROVIDER == "groq"

    def test_llm_provider_accepts_valid_value_ollama(self):
        """LLM_PROVIDER must accept 'ollama'."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
            LLM_PROVIDER="ollama",
        )
        assert s.LLM_PROVIDER == "ollama"

    def test_llm_provider_accepts_valid_value_openai(self):
        """LLM_PROVIDER must accept 'openai'."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
            LLM_PROVIDER="openai",
        )
        assert s.LLM_PROVIDER == "openai"


class TestLLMSettingsDefaults:
    """Verify LLM settings have sensible defaults."""

    def test_llm_timeout_default_is_30(self):
        """LLM_TIMEOUT should default to 30 seconds."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert s.LLM_TIMEOUT == 30

    def test_llm_max_tokens_default_is_2048(self):
        """LLM_MAX_TOKENS should default to 2048."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert s.LLM_MAX_TOKENS == 2048

    def test_llm_temperature_default_is_01(self):
        """LLM_TEMPERATURE should default to 0.1."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert s.LLM_TEMPERATURE == 0.1

    def test_llm_provider_default_is_groq(self):
        """LLM_PROVIDER should default to 'groq'."""
        from app.core.config import Settings

        s = Settings(
            SECRET_KEY="x" * 32,
            DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
            DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
            POSTGRES_USER="test",
            POSTGRES_PASSWORD="test",
            POSTGRES_DB="test",
            GROQ_API_KEY="gsk_test_key",
        )
        assert s.LLM_PROVIDER == "groq"
