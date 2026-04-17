from __future__ import annotations

import re
from typing import ClassVar, Protocol, runtime_checkable

import httpx

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

_PROVIDER_CLASSES: dict[str, type] = {}  # filled by _register_providers at import time


def _register_providers() -> None:
    """Register all concrete provider classes keyed by provider name."""
    # OpenAI-compatible family (shared transport /v1/chat/completions)
    for _name in (
        "groq",
        "ollama",
        "openai",
        "mistral",
        "cohere",
        "together",
        "huggingface",
    ):
        _PROVIDER_CLASSES[_name] = OpenAICompatProvider
    _PROVIDER_CLASSES["anthropic"] = AnthropicProvider
    _PROVIDER_CLASSES["gemini"] = GeminiProvider


def _create_provider(provider_name: str) -> "LLMProvider":
    """Create a new (uncached) provider instance for the given provider name.

    Raises
    ------
    LLMResponseError
        If the provider name is not recognised.
    """
    if not _PROVIDER_CLASSES:
        _register_providers()

    provider_cls = _PROVIDER_CLASSES.get(provider_name)
    if provider_cls is None:
        raise LLMResponseError(
            f"Unknown LLM provider: {provider_name!r}. "
            f"Supported: {sorted(_PROVIDER_CLASSES)}"
        )

    # -------------------------------------------------------------------------
    # Per-provider configuration (model, api_key, base_url)
    # -------------------------------------------------------------------------
    if provider_name == "ollama":
        base_url = getattr(settings, "OLLAMA_URL", "http://localhost:11434")
        api_key = ""  # Ollama has no auth
        model = settings.OLLAMA_MODEL
    elif provider_name == "groq":
        base_url = "https://api.groq.com/v1"
        api_key = settings.GROQ_API_KEY
        model = settings.GROQ_MODEL
    elif provider_name == "openai":
        base_url = "https://api.openai.com/v1"
        api_key = settings.OPENAI_API_KEY or ""
        model = "gpt-4o"  # default; user can override via env
    elif provider_name == "anthropic":
        api_key = settings.ANTHROPIC_API_KEY or ""
        model = "claude-3-5-haiku-20241107"  # default
    elif provider_name == "gemini":
        api_key = settings.GEMINI_API_KEY or ""
        model = "gemini-2.0-flash"  # default
    elif provider_name == "mistral":
        base_url = "https://api.mistral.ai/v1"
        api_key = settings.MISTRAL_API_KEY or ""
        model = "mistral-large-latest"
    elif provider_name == "cohere":
        base_url = "https://api.cohere.ai/v1"
        api_key = settings.COHERE_API_KEY or ""
        model = "command-r-plus"
    elif provider_name == "together":
        base_url = "https://api.together.xyz/v1"
        api_key = settings.TOGETHER_API_KEY or ""
        model = "mistralai/Mistral-7B-Instruct-v0.3"
    elif provider_name == "huggingface":
        base_url = "https://api-inference.huggingface.co/v1"
        api_key = settings.HUGGINGFACE_API_KEY or ""
        model = "meta-llama/Llama-3.3-70B-Instruct"
    else:
        # Should not reach here (handled by _PROVIDER_CLASSES.get above)
        raise LLMResponseError(f"Unsupported provider: {provider_name!r}")

    # -------------------------------------------------------------------------
    # Instantiate the concrete class
    # -------------------------------------------------------------------------
    kwargs: dict[str, object] = dict(
        api_key=api_key,
        model=model,
        timeout=settings.LLM_TIMEOUT,
    )
    if provider_name in ("groq", "ollama", "mistral", "cohere", "together", "huggingface", "openai"):
        kwargs["base_url"] = base_url

    return provider_cls(**kwargs)  # type: ignore[arg-type]


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
    ) -> None:
        self._api_key = api_key
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
            _redact_credentials(self.BASE_URL),
        )

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                response = await client.post(self.BASE_URL, json=payload, headers=headers)
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
    ) -> None:
        self._api_key = api_key
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
        LLMResponseError
            For any other non-OK response.
        LLMError
            For transport-level failures.
        """
        url = f"{self.BASE_URL}/models/{self._model}:generateContent"
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
