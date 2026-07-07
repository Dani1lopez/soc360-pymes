"""LLM provider factory: registry, instantiation, and singleton cache."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.core._provider_names import _PROVIDER_NAMES
from app.core.config import settings
from app.core.exceptions import LLMResponseError
from app.core.llm.config import _llm_logger
from app.core.llm.providers import (
    AnthropicProvider,
    GeminiProvider,
    OpenAICompatProvider,
)

# Singleton cache: one provider instance per provider name, per process.
_llm_singletons: dict[str, "LLMProvider"] = {}

_PROVIDER_REGISTRY: dict[str, "ProviderEntry"] = {}
# filled by _register_providers() on first _create_provider call


@dataclass(slots=True, frozen=True)
class ProviderEntry:
    """Single source of truth for one LLM provider's configuration."""

    cls: type
    api_key_attr: str | None
    model_default: str
    base_url_attr: str | None
    base_url_default: str | None
    url_normalizer: Callable[[str], str] | None


def _register_providers() -> None:
    """Build the provider registry with all 9 supported providers.

    Called lazily on first ``_create_provider()`` invocation.
    Includes a drift assertion that catches mismatches between
    ``_PROVIDER_NAMES`` (in ``_provider_names.py``) and the
    registry keys at import time.
    """
    if _PROVIDER_REGISTRY:
        return

    _PROVIDER_REGISTRY.update({
        "groq": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="GROQ_API_KEY",
            model_default="llama-3.3-70b-versatile",
            base_url_attr=None, base_url_default="https://api.groq.com/v1",
            url_normalizer=None,
        ),
        "ollama": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr=None,
            model_default="llama3.2",
            base_url_attr="OLLAMA_URL", base_url_default="http://localhost:11434",
            url_normalizer=OpenAICompatProvider._normalize_ollama_url,
        ),
        "openai": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="OPENAI_API_KEY",
            model_default="gpt-4o",
            base_url_attr=None, base_url_default="https://api.openai.com/v1",
            url_normalizer=None,
        ),
        "anthropic": ProviderEntry(
            cls=AnthropicProvider, api_key_attr="ANTHROPIC_API_KEY",
            model_default="claude-3-5-haiku-20241107",
            base_url_attr="ANTHROPIC_BASE_URL", base_url_default=None,
            url_normalizer=None,
        ),
        "gemini": ProviderEntry(
            cls=GeminiProvider, api_key_attr="GEMINI_API_KEY",
            model_default="gemini-2.0-flash",
            base_url_attr="GEMINI_BASE_URL", base_url_default=None,
            url_normalizer=None,
        ),
        "mistral": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="MISTRAL_API_KEY",
            model_default="mistral-large-latest",
            base_url_attr=None, base_url_default="https://api.mistral.ai/v1",
            url_normalizer=None,
        ),
        "cohere": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="COHERE_API_KEY",
            model_default="command-r-plus",
            base_url_attr=None, base_url_default="https://api.cohere.ai/v1",
            url_normalizer=None,
        ),
        "together": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="TOGETHER_API_KEY",
            model_default="mistralai/Mistral-7B-Instruct-v0.3",
            base_url_attr=None, base_url_default="https://api.together.xyz/v1",
            url_normalizer=None,
        ),
        "huggingface": ProviderEntry(
            cls=OpenAICompatProvider, api_key_attr="HUGGINGFACE_API_KEY",
            model_default="meta-llama/Llama-3.3-70B-Instruct",
            base_url_attr=None, base_url_default="https://api-inference.huggingface.co/v1",
            url_normalizer=None,
        ),
    })

    # Runtime assertion: catch drift between _provider_names.py and registry.
    # If a developer adds a ProviderEntry but forgets to update _PROVIDER_NAMES,
    # the validator rejects a valid provider — this assertion catches the mismatch
    # at import time.
    assert set(_PROVIDER_REGISTRY.keys()) == _PROVIDER_NAMES, (
        f"Provider registry and _PROVIDER_NAMES are out of sync. "
        f"Registry: {sorted(_PROVIDER_REGISTRY.keys())}. "
        f"_PROVIDER_NAMES: {sorted(_PROVIDER_NAMES)}. "
        f"Update app/core/_provider_names.py to match."
    )


def _create_provider(provider_name: str) -> "LLMProvider":
    """Create a new (uncached) provider instance for the given provider name.

    Generic resolver — zero ``if/elif`` on provider name. All per-provider
    configuration lives in ``ProviderEntry`` inside ``_PROVIDER_REGISTRY``.

    Raises
    ------
    LLMResponseError
        If the provider name is empty, unknown, or required configuration
        (model, API key) is missing.
    """
    # Normalize
    name = provider_name.strip().lower()
    if not name:
        raise LLMResponseError("LLM provider name must not be empty")

    if not _PROVIDER_REGISTRY:
        _register_providers()

    entry = _PROVIDER_REGISTRY.get(name)
    if entry is None:
        raise LLMResponseError(
            f"Unknown LLM provider: {name!r}. "
            f"Supported: {sorted(_PROVIDER_REGISTRY)}"
        )

    # Model: convention {NAME}_MODEL, with explicit None vs empty-string handling.
    # None  → use entry.model_default (env var not set at all)
    # ""    → raise LLMResponseError  (env var explicitly set to empty)
    # value → use it as-is
    model = getattr(settings, f"{name.upper()}_MODEL", None)
    if model is None:
        model = entry.model_default
    if not model:
        raise LLMResponseError(f"Model not configured for provider {name!r}")

    # API key: None attr = skip (ollama); None value = use "" (backcompat);
    # explicitly empty string = error (spec R06b)
    if entry.api_key_attr is not None:
        api_key = getattr(settings, entry.api_key_attr, None)
        if api_key is not None and not api_key:
            raise LLMResponseError(
                f"API key is required for provider {name!r} "
                f"but {entry.api_key_attr} is empty"
            )
        if api_key is None:
            api_key = ""
    else:
        api_key = ""

    # Base URL: attr → Settings, else hardcoded; then normalizer
    base_url: str | None = None
    if entry.base_url_attr is not None:
        base_url = getattr(settings, entry.base_url_attr, None) or entry.base_url_default
    elif entry.base_url_default is not None:
        base_url = entry.base_url_default

    if base_url is not None and entry.url_normalizer is not None:
        base_url = entry.url_normalizer(base_url)

    kwargs: dict[str, object] = dict(
        api_key=api_key,
        model=model,
        timeout=settings.LLM_TIMEOUT,
    )
    if base_url is not None:
        kwargs["base_url"] = base_url

    return entry.cls(**kwargs)  # type: ignore[arg-type]


def get_llm_provider() -> "LLMProvider":
    """Return the singleton LLM provider for the configured provider name.

    This is the FastAPI dependency entrypoint. The first call instantiates
    the provider; subsequent calls return the cached instance.
    """
    provider_name = settings.LLM_PROVIDER

    if provider_name not in _llm_singletons:
        _llm_singletons[provider_name] = _create_provider(provider_name)

    return _llm_singletons[provider_name]
