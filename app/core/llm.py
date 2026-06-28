from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, ClassVar, Protocol, runtime_checkable

import httpx

from app.core._provider_names import _PROVIDER_NAMES
from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import (
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)

# Module-level logger for the LLM layer.
# Uses the shared project logger so redaction stays consistent everywhere.
_llm_logger = get_logger("app.core.llm")

# Compiled pattern to detect common API key formats in strings.
_API_KEY_PATTERN = re.compile(
    r"(sk-|gsk_|api_|token_|bearer_)([a-zA-Z0-9_\-]{8,})",
    re.IGNORECASE,
)


def _redact_credentials(text: str) -> str:
    """Replace any API-key-like substrings with [REDACTED].

    Covers patterns like sk-..., gsk_..., api_key values in URLs, and Bearer tokens.
    """
    # Redact URL query params that contain 'api_key', 'key', 'token'
    text = re.sub(r"([?&](?:api_?key|key|token|bearer)=)([^&\s]+)", r"\1[REDACTED]", text)
    # Redact Bearer token values in Authorization headers
    text = re.sub(r"(Bearer )([a-zA-Z0-9_\-]{8,})", r"\1[REDACTED]", text)
    # Redact common API key prefixes with their values
    text = _API_KEY_PATTERN.sub(r"\1[REDACTED]", text)
    return text

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


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal async interface for LLM providers."""

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send a prompt to the LLM and return the raw text response."""
        ...


class OpenAICompatProvider:
    """
    Async provider for OpenAI-compatible endpoints.

    Covers Groq, Ollama, OpenAI, Mistral, Cohere, Together AI,
    and HuggingFace Inference API — all sharing the same
    ``/v1/chat/completions`` call shape.
    """

    DEFAULT_BASE_URL: ClassVar[str] = "https://api.openai.com/v1"
    ENDPOINT: ClassVar[str] = "/chat/completions"

    @staticmethod
    def _normalize_ollama_url(url: str) -> str:
        """Normalize an Ollama base URL to include the /v1 API path.

        Strips trailing slashes and appends ``/v1`` if not already present,
        so ``http://localhost:11434`` becomes ``http://localhost:11434/v1``.
        Already-correct URLs (already ending in ``/v1``) pass through unchanged.
        """
        url = url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        model: str,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model = model
        self._timeout = timeout

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Send a prompt and return the raw text response.

        Raises
        ------
        LLMTimeoutError
            When the request exceeds ``self._timeout``.
        LLMRateLimitError
            When the provider returns HTTP 429.
        LLMContentFilterError
            When the provider returns HTTP 451.
        LLMResponseError
            For any other non-OK response.
        LLMError
            For transport-level failures.
        """
        url = f"{self._base_url}{self.ENDPOINT}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        _llm_logger.debug(
            "LLM call: provider=OpenAICompatProvider model=%s endpoint=%s",
            self._model,
            _redact_credentials(url),
        )

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            _llm_logger.warning("LLM timeout: provider=OpenAICompatProvider timeout=%ss", self._timeout)
            raise LLMTimeoutError(
                f"Request timed out after {self._timeout}s"
            ) from None
        except httpx.HTTPError as exc:
            _llm_logger.warning("LLM HTTP error: provider=OpenAICompatProvider error=%s", exc)
            raise LLMError(f"HTTP error during request: {exc}") from exc

        if response.status_code == 429:
            _llm_logger.warning("LLM rate limit: provider=OpenAICompatProvider status=429")
            raise LLMRateLimitError(
                "Rate limit hit (429) — not retried automatically"
            ) from None
        if response.status_code == 451:
            _llm_logger.warning("LLM content filtered: provider=OpenAICompatProvider status=451")
            raise LLMContentFilterError(
                "Content filtered by provider (451)"
            ) from None
        if not response.is_success:
            _llm_logger.warning(
                "LLM non-success response: provider=OpenAICompatProvider status=%s",
                response.status_code,
            )
            raise LLMResponseError(
                f"Provider returned {response.status_code}: {response.text[:200]}"
            ) from None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except Exception:
            _llm_logger.warning("LLM parse error: provider=OpenAICompatProvider")
            raise LLMResponseError(
                f"Could not parse response body: {response.text[:200]}"
            ) from None

        _llm_logger.debug("LLM success: provider=OpenAICompatProvider model=%s", self._model)
        return content


class AnthropicProvider:
    """
    Async provider for Anthropic's Claude API.

    Uses the ``/v1/messages`` endpoint with the
    ``anthropic-version: 2023-06-01`` header.
    """

    BASE_URL: ClassVar[str] = "https://api.anthropic.com/v1/messages"
    API_VERSION: ClassVar[str] = "2023-06-01"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        timeout: int = 30,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._base_url = base_url or self.BASE_URL

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Send a prompt and return the raw text response.

        Raises
        ------
        LLMTimeoutError
            When the request exceeds ``self._timeout``.
        LLMRateLimitError
            When the provider returns HTTP 429.
        LLMContentFilterError
            When the provider returns HTTP 451.
        LLMResponseError
            For any other non-OK response.
        LLMError
            For transport-level failures.
        """
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        _llm_logger.debug(
            "LLM call: provider=Anthropic model=%s endpoint=%s",
            self._model,
            _redact_credentials(self._base_url),
        )

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(self._base_url, json=payload, headers=headers)
        except httpx.TimeoutException:
            _llm_logger.warning("LLM timeout: provider=Anthropic timeout=%ss", self._timeout)
            raise LLMTimeoutError(
                f"Request timed out after {self._timeout}s"
            ) from None
        except httpx.HTTPError as exc:
            _llm_logger.warning("LLM HTTP error: provider=Anthropic error=%s", exc)
            raise LLMError(f"HTTP error during request: {exc}") from exc

        if response.status_code == 429:
            _llm_logger.warning("LLM rate limit: provider=Anthropic status=429")
            raise LLMRateLimitError(
                "Rate limit hit (429) — not retried automatically"
            ) from None
        if response.status_code == 451:
            _llm_logger.warning("LLM content filtered: provider=Anthropic status=451")
            raise LLMContentFilterError(
                "Content filtered by provider (451)"
            ) from None
        if not response.is_success:
            _llm_logger.warning(
                "LLM non-success response: provider=Anthropic status=%s",
                response.status_code,
            )
            raise LLMResponseError(
                f"Provider returned {response.status_code}: {response.text[:200]}"
            ) from None

        try:
            data = response.json()
            content = data["content"][0]["text"]
        except Exception:
            _llm_logger.warning("LLM parse error: provider=Anthropic")
            raise LLMResponseError(
                f"Could not parse response body: {response.text[:200]}"
            ) from None

        _llm_logger.debug("LLM success: provider=Anthropic model=%s", self._model)
        return content


class GeminiProvider:
    """
    Async provider for Google Gemini models via the REST API.

    Uses the ``/v1beta/models/{model}:generateContent`` endpoint.
    """

    BASE_URL: ClassVar[str] = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        timeout: int = 30,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._base_url = base_url or self.BASE_URL

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Send a prompt and return the raw text response.

        Raises
        ------
        LLMTimeoutError
            When the request exceeds ``self._timeout``.
        LLMRateLimitError
            When the provider returns HTTP 429.
        LLMResponseError
            For any other non-OK response.
        LLMError
            For transport-level failures.
        """
        url = f"{self._base_url}/models/{self._model}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }

        _llm_logger.debug(
            "LLM call: provider=Gemini model=%s endpoint=%s",
            self._model,
            _redact_credentials(url),
        )

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException:
            _llm_logger.warning("LLM timeout: provider=Gemini timeout=%ss", self._timeout)
            raise LLMTimeoutError(
                f"Request timed out after {self._timeout}s"
            ) from None
        except httpx.HTTPError as exc:
            _llm_logger.warning("LLM HTTP error: provider=Gemini error=%s", exc)
            raise LLMError(f"HTTP error during request: {exc}") from exc

        if response.status_code == 429:
            _llm_logger.warning("LLM rate limit: provider=Gemini status=429")
            raise LLMRateLimitError(
                "Rate limit hit (429) — not retried automatically"
            ) from None
        if response.status_code == 451:
            _llm_logger.warning("LLM content filtered: provider=Gemini status=451")
            raise LLMContentFilterError(
                "Content filtered by provider (451)"
            ) from None
        if not response.is_success:
            _llm_logger.warning(
                "LLM non-success response: provider=Gemini status=%s",
                response.status_code,
            )
            raise LLMResponseError(
                f"Provider returned {response.status_code}: {response.text[:200]}"
            ) from None

        try:
            data = response.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            _llm_logger.warning("LLM parse error: provider=Gemini")
            raise LLMResponseError(
                f"Could not parse response body: {response.text[:200]}"
            ) from None

        _llm_logger.debug("LLM success: provider=Gemini model=%s", self._model)
        return content


class MockLLMProvider:
    """
    Async test double for LLM providers.

    Returns a pre-configured response after an optional delay.
    No network calls are made. Satisfies the LLMProvider protocol
    at runtime so it can be substituted for any concrete provider.
    """

    def __init__(
        self,
        response_text: str = "mock response",
        delay_seconds: float = 0.0,
    ) -> None:
        self._response_text = response_text
        self._delay_seconds = delay_seconds

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Return the configured response text after the configured delay."""
        if self._delay_seconds > 0:
            import asyncio
            await asyncio.sleep(self._delay_seconds)
        return self._response_text


async def llm_safe_complete(
    provider: "LLMProvider",
    prompt: str,
    max_tokens: int,
    temperature: float,
) -> tuple[str, bool]:
    """Call provider.complete() and return (text, failed=False) on success.

    On any LLMError subtype, returns ("", True) instead of raising.
    This lets callers set llm_failed=True on ScanState and continue
    non-blocking without the scan crashing on a provider outage.

    The helper performs no network calls itself — the provider does.
    """
    try:
        text = await provider.complete(prompt, max_tokens, temperature)
        return text, False
    except LLMError:
        return "", True
