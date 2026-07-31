from __future__ import annotations

import os
from collections import Counter
from math import log2
from typing import ClassVar

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core._provider_names import _PROVIDER_NAMES

# Secret key strength thresholds (issue #250)
# ⚠️  BREAKING CHANGE: raising MIN_SECRET_KEY_LENGTH from 32 to 128 will
# reject existing deployments with shorter keys. See .env.example for
# migration instructions.
MIN_SECRET_KEY_LENGTH = 128
MIN_SECRET_KEY_ENTROPY_BITS_PER_CHAR = 3.0
MAX_SECRET_KEY_CHAR_FREQUENCY_RATIO = 0.5

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    #Aplicacion
    ENVIRONMENT: str
    APP_NAME: str = "SOC 360 PYMEs"
    SECRET_KEY: str
    
    #Base de datos
    DATABASE_URL: str
    DATABASE_URL_MIGRATION: str 
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    # Per-connection safety nets (issue #134) — prevent runaway queries and
    # indefinite lock waits from starving the pool.
    DB_STATEMENT_TIMEOUT_MS: int = 30_000
    DB_LOCK_TIMEOUT_MS: int = 5_000
    
    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # AI
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    USE_OLLAMA: bool = False
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.2"

    # LLM Abstraction
    LLM_PROVIDER: str = "groq"
    LLM_TIMEOUT: int = 30
    LLM_MAX_TOKENS: int = 2048
    LLM_TEMPERATURE: float = 0.1

    # Per-provider API keys (None = not configured for that provider)
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    MISTRAL_API_KEY: str | None = None
    COHERE_API_KEY: str | None = None
    TOGETHER_API_KEY: str | None = None
    HUGGINGFACE_API_KEY: str | None = None

    # Per-provider model defaults (env-overridable via {NAME}_MODEL)
    OPENAI_MODEL: str = "gpt-4o"
    ANTHROPIC_MODEL: str = "claude-3-5-haiku-20241107"
    GEMINI_MODEL: str = "gemini-2.0-flash"
    MISTRAL_MODEL: str = "mistral-large-latest"
    COHERE_MODEL: str = "command-r-plus"
    TOGETHER_MODEL: str = "mistralai/Mistral-7B-Instruct-v0.3"
    HUGGINGFACE_MODEL: str = "meta-llama/Llama-3.3-70B-Instruct"

    # Per-provider base URL overrides (None = use provider class default)
    ANTHROPIC_BASE_URL: str | None = None
    GEMINI_BASE_URL: str | None = None

    # Event Bus (Redis Streams)
    EVENT_STREAM_PREFIX: str = "events"
    EVENT_CONSUMER_GROUP: str = "soc360-consumers"
    EVENT_MAX_RETRIES: int = 3
    EVENT_STREAM_MAXLEN: int = 100000
    EVENT_STREAM_MAXAGE_SECONDS: int = 604800
    EVENT_PENDING_LAG_THRESHOLD: int = 100
    # TTL for the per-message retry counter hash (issue #127). Stale keys from
    # crashed processes are reclaimed automatically after this many seconds.
    EVENT_RETRY_TTL_SECONDS: int = 86400

    #Redis — structured settings; REDIS_URL is rejected (PR1 #260)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: SecretStr = SecretStr("")
    REDIS_MAX_CONNECTIONS: int = 20
    # Startup ping retry — rides out transient Redis blips during lifespan (issue #128)
    REDIS_STARTUP_MAX_ATTEMPTS: int = 3
    REDIS_STARTUP_BACKOFF_BASE_SECONDS: float = 1.0

    # Metrics endpoint auth + outage translation (PR4 #260)
    # Lifecycle: METRICS_TOKEN is mandatory in production; METRICS_TOKEN_PREVIOUS
    # is optional and exists only to enable zero-downtime rotation overlap.
    METRICS_TOKEN: SecretStr | None = None
    METRICS_TOKEN_PREVIOUS: SecretStr | None = None
    # Retry-After (seconds) used by the RedisOutageError handler. Range 1..300.
    REDIS_OUTAGE_RETRY_AFTER_SECONDS: int = 30

    # Distributed lock lease settings (PR5a #260)
    LOCK_KEY_SECRET: SecretStr | None = None
    LOCK_DEFAULT_TTL_SECONDS: int = 30
    LOCK_DEFAULT_RETRY_AFTER_SECONDS: int = 15
    LOCK_RETRY_AFTER_SECONDS: int | None = None
    # Security policy: deliberately not an environment-overridable field.
    LOCK_MIN_TTL_SECONDS: ClassVar[int] = 1

    def __init__(self, **values):
        if any(str(key).upper() == "REDIS_URL" for key in values):
            raise ValueError(
                "REDIS_URL is no longer supported. "
                "Use REDIS_HOST, REDIS_PORT, REDIS_DB, and REDIS_PASSWORD instead."
            )
        super().__init__(**values)
    
    # Rate Limiting (progressive lockout)
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 86400  # 24h — auto-cleanup TTL for rate limit keys

    #CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    #Proxy
    TRUSTED_PROXIES: list[str] = []
    
    #Validators
    
    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_strength(cls, v: str) -> str:
        if len(v) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(
                f"SECRET_KEY debe tener mínimo {MIN_SECRET_KEY_LENGTH} caracteres"
            )

        # Reject keys where >50 % of characters are the same (low-entropy pattern)
        counts = Counter(v)
        max_freq_ratio = max(counts.values()) / len(v)
        if max_freq_ratio > MAX_SECRET_KEY_CHAR_FREQUENCY_RATIO:
            raise ValueError(
                "SECRET_KEY tiene muy poca entropía: "
                "no debe tener más del 50% de caracteres repetidos"
            )

        # Shannon entropy check (reject below 3.0 bits/char)
        entropy = -sum(
            (c / len(v)) * log2(c / len(v))
            for c in counts.values()
        )
        if entropy < MIN_SECRET_KEY_ENTROPY_BITS_PER_CHAR:
            raise ValueError(
                f"SECRET_KEY tiene muy poca entropía: "
                f"la entropía ({entropy:.2f} bits/char) es menor que "
                f"{MIN_SECRET_KEY_ENTROPY_BITS_PER_CHAR} bits/char"
            )

        return v
    
    @field_validator("ENVIRONMENT")
    @classmethod
    def environment_valid(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"ENVIRONMENT debe ser uno de: {allowed}")
        return v
    
    @field_validator("JWT_ALGORITHM")
    @classmethod
    def algorithm_valid(cls, v: str) -> str:
        allowed = {"HS256", "HS384", "HS512"}
        if v not in allowed:
            raise ValueError(f"JWT_ALGORITHM debe ser uno de: {allowed}")
        return v
    
    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def token_expiry_sane(cls, v: int) -> int:
        if not (1 <= v <= 60):
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES debe estar entre 1 y 60")
        return v
    
    @field_validator("CORS_ORIGINS")
    @classmethod
    def cors_not_wildcard(cls, v: list[str]) -> list[str]:
        if "*" in v:
            raise ValueError("CORS_ORIGINS no puede contener wildcard '*'")
        return v
    
    @model_validator(mode="before")
    @classmethod
    def reject_redis_url(cls, data):
        """Reject REDIS_URL from kwargs, environment, or dotenv (PR1 #260)."""
        dotenv_or_kwargs = isinstance(data, dict) and any(
            str(key).upper() == "REDIS_URL" for key in data
        )
        if dotenv_or_kwargs or any(key.upper() == "REDIS_URL" for key in os.environ):
            raise ValueError(
                "REDIS_URL is no longer supported. "
                "Use REDIS_HOST, REDIS_PORT, REDIS_DB, and REDIS_PASSWORD instead."
            )
        return data

    @model_validator(mode="after")
    def redis_password_required_in_production(self) -> Settings:
        """Production must have a non-empty REDIS_PASSWORD."""
        if self.ENVIRONMENT == "production":
            if not self.REDIS_PASSWORD.get_secret_value():
                raise ValueError("REDIS_PASSWORD is required in production")
        return self


    @field_validator("LLM_PROVIDER")
    @classmethod
    def llm_provider_valid(cls, v: str) -> str:
        if v.lower() not in _PROVIDER_NAMES:
            raise ValueError(f"LLM_PROVIDER debe ser uno de: {sorted(_PROVIDER_NAMES)}")
        return v.lower()

    @field_validator("DB_STATEMENT_TIMEOUT_MS", "DB_LOCK_TIMEOUT_MS")
    @classmethod
    def db_timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(
                "DB timeout values must be positive integers (milliseconds); "
                "PostgreSQL treats 0 as 'disabled', which defeats the safety net"
            )
        return v

    @model_validator(mode="after")
    def groq_key_required_for_groq(self) -> Settings:
        if self.LLM_PROVIDER == "groq":
            if not self.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY es requerido cuando LLM_PROVIDER='groq'")
            if not self.GROQ_API_KEY.startswith("gsk_"):
                raise ValueError("GROQ_API_KEY debe empezar con 'gsk_'")
        return self

    # ─── PR4 #260 — Metrics credential lifecycle + Redis-outage retry translation

    @field_validator("REDIS_OUTAGE_RETRY_AFTER_SECONDS")
    @classmethod
    def retry_after_in_range(cls, v: int) -> int:
        """Retry-After MUST be between 1 and 300 seconds inclusive."""
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError("REDIS_OUTAGE_RETRY_AFTER_SECONDS must be an integer")
        if not (1 <= v <= 300):
            raise ValueError(
                "REDIS_OUTAGE_RETRY_AFTER_SECONDS must be between 1 and 300 seconds"
            )
        return v

    @field_validator("LOCK_RETRY_AFTER_SECONDS")
    @classmethod
    def lock_retry_after_in_range(cls, v: int | None) -> int | None:
        if v is not None and (
            not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 300
        ):
            raise ValueError(
                "LOCK_RETRY_AFTER_SECONDS must be between 1 and 300 seconds"
            )
        return v

    @model_validator(mode="after")
    def metrics_token_required_in_production(self) -> Settings:
        """Production MUST fail fast at startup if METRICS_TOKEN is empty.

        ``METRICS_TOKEN_PREVIOUS`` alone MUST NOT satisfy production (it only
        supports rotation overlap, not initial deploy).
        """
        if self.ENVIRONMENT == "production":
            current = self.METRICS_TOKEN.get_secret_value() if self.METRICS_TOKEN else ""
            if not current:
                raise ValueError(
                    "METRICS_TOKEN is required in production (METRICS_TOKEN_PREVIOUS alone does not satisfy)"
                )
        return self

    @model_validator(mode="after")
    def metrics_tokens_must_differ(self) -> Settings:
        """``METRICS_TOKEN`` and ``METRICS_TOKEN_PREVIOUS`` MUST differ.

        A "rotation" to the same value would leave the previous token in
        service forever; reject at boot so the misconfiguration is loud.
        """
        if self.METRICS_TOKEN and self.METRICS_TOKEN_PREVIOUS:
            current = self.METRICS_TOKEN.get_secret_value()
            previous = self.METRICS_TOKEN_PREVIOUS.get_secret_value()
            if current and previous and current == previous:
                raise ValueError(
                    "METRICS_TOKEN_PREVIOUS must differ from METRICS_TOKEN"
                )
        return self

    @model_validator(mode="after")
    def lock_key_secret_required_in_production(self) -> Settings:
        secret = self.LOCK_KEY_SECRET.get_secret_value() if self.LOCK_KEY_SECRET else ""
        if self.ENVIRONMENT == "production" and self.LOCK_KEY_SECRET is not None and len(secret.encode()) < 32:
            raise ValueError("LOCK_KEY_SECRET must be at least 32 bytes in production")
        return self


settings = Settings()
