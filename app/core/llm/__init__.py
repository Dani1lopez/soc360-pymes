"""LLM provider abstraction: factory, providers, and public API."""
from __future__ import annotations

from app.core.config import settings  # noqa: F401 — re-exported for test monkeypatch compat
from app.core.llm.config import (  # noqa: F401
    LLM_RETRY_BACKOFF_BASE_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
    LLM_RETRYABLE_STATUS_CODES,
    _API_KEY_PATTERN,
    _llm_logger,
    _redact_credentials,
)
from app.core.llm.factory import (  # noqa: F401
    ProviderEntry,
    _PROVIDER_REGISTRY,
    _create_provider,
    _llm_singletons,
    _register_providers,
    get_llm_provider,
)
from app.core.llm.providers import (  # noqa: F401
    AnthropicProvider,
    GeminiProvider,
    LLMProvider,
    MockLLMProvider,
    OpenAICompatProvider,
    _BaseHTTPProvider,
    llm_safe_complete,
)
