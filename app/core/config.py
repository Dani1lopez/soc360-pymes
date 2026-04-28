from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
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
    
    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # AI
    GROQ_API_KEY: str
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
    
    # Event Bus (Redis Streams)
    EVENT_STREAM_PREFIX: str = "events"
    EVENT_CONSUMER_GROUP: str = "soc360-consumers"
    EVENT_MAX_RETRIES: int = 3
    EVENT_STREAM_MAXLEN: int = 100000
    EVENT_STREAM_MAXAGE_SECONDS: int = 604800
    EVENT_PENDING_LAG_THRESHOLD: int = 100

    #Redis
    REDIS_PASSWORD: str | None = None
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 20
    
    #CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]

    #Proxy
    TRUSTED_PROXIES: list[str] = []
    
    #Validators
    
    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_strength(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY debe tener mínimo 32 caracteres")
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
    
    @field_validator("REDIS_URL")
    @classmethod
    def redis_auth_in_production(cls, v: str, info) -> str:
        environment = info.data.get("ENVIRONMENT", "development")
        redis_password = info.data.get("REDIS_PASSWORD")
        if redis_password and "@" not in v:
            raise ValueError("REDIS_URL debe incluir autenticación cuando REDIS_PASSWORD está configurado")
        if environment == "production" and "@" not in v:
            raise ValueError("REDIS_URL debe incluir autenticación en producción")
        if environment == "production" and not redis_password:
            raise ValueError("REDIS_PASSWORD es requerido en producción")
        return v
    
    @field_validator("GROQ_API_KEY")
    @classmethod
    def groq_key_format(cls, v: str) -> str:
        if not v.startswith("gsk_"):
            raise ValueError("GROQ_API_KEY debe empezar con 'gsk_'")
        return v

    @field_validator("LLM_PROVIDER")
    @classmethod
    def llm_provider_valid(cls, v: str) -> str:
        allowed = {
            "groq", "ollama", "openai", "anthropic",
            "gemini", "mistral", "cohere", "together", "huggingface",
        }
        if v.lower() not in allowed:
            raise ValueError(f"LLM_PROVIDER debe ser uno de: {sorted(allowed)}")
        return v.lower()


settings = Settings()
