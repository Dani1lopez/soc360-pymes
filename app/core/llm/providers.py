"""LLM provider classes: protocol, base HTTP, concrete providers, and test double."""
from __future__ import annotations

import asyncio
from typing import ClassVar, Protocol, runtime_checkable

import httpx

from app.core.llm.config import (
    LLM_RETRY_BACKOFF_BASE_SECONDS,
    LLM_RETRY_MAX_ATTEMPTS,
    LLM_RETRYABLE_STATUS_CODES,
    _llm_logger,
    _redact_credentials,
)
from app.core.exceptions import (
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)


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


class _BaseHTTPProvider:
    """Shared HTTP request logic with retry/backoff for transient errors (issue #137).

    Subclasses implement:
    - ``_build_request()`` → returns (url, headers, payload)
    - ``_parse_response(data)`` → extracts the text content from the JSON response

    The base class handles:
    - HTTP transport (httpx.AsyncClient)
    - Timeout handling
    - Status code mapping to exceptions
    - Retry with exponential backoff for 429 and 5xx
    - Logging with credential redaction
    """

    PROVIDER_NAME: ClassVar[str] = "BaseHTTPProvider"

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
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))

    def _build_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, str], dict[str, object]]:
        """Return (url, headers, payload) for the HTTP POST."""
        raise NotImplementedError

    def _parse_response(self, data: dict) -> str:
        """Extract the text content from the parsed JSON response."""
        raise NotImplementedError

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Send a prompt and return the raw text response.

        Retries up to ``LLM_RETRY_MAX_ATTEMPTS`` times on 429 and 5xx
        with exponential backoff (1s, 2s, 4s by default).

        Raises
        ------
        LLMTimeoutError
            When the request exceeds ``self._timeout``.
        LLMRateLimitError
            When the provider returns HTTP 429 after all retries exhausted.
        LLMContentFilterError
            When the provider returns HTTP 451.
        LLMResponseError
            For any other non-OK response or parse failure.
        LLMError
            For transport-level failures.
        """
        url, headers, payload = self._build_request(prompt, max_tokens, temperature)

        _llm_logger.debug(
            "LLM call: provider=%s model=%s endpoint=%s",
            self.PROVIDER_NAME,
            self._model,
            _redact_credentials(url),
        )

        last_error: Exception | None = None
        for attempt in range(1, LLM_RETRY_MAX_ATTEMPTS + 1):
            try:
                response = await self._client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException:
                _llm_logger.warning(
                    "LLM timeout: provider=%s timeout=%ss",
                    self.PROVIDER_NAME,
                    self._timeout,
                )
                raise LLMTimeoutError(
                    f"Request timed out after {self._timeout}s"
                ) from None
            except httpx.HTTPError as exc:
                _llm_logger.warning(
                    "LLM HTTP error: provider=%s error=%s",
                    self.PROVIDER_NAME,
                    exc,
                )
                raise LLMError(f"HTTP error during request: {exc}") from exc

            # 451 Content Filtered — never retry
            if response.status_code == 451:
                _llm_logger.warning(
                    "LLM content filtered: provider=%s status=451",
                    self.PROVIDER_NAME,
                )
                raise LLMContentFilterError(
                    "Content filtered by provider (451)"
                ) from None

            # 429 Rate Limit — retry with backoff
            if response.status_code == 429:
                if attempt < LLM_RETRY_MAX_ATTEMPTS:
                    wait = LLM_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    _llm_logger.warning(
                        "LLM rate limit: provider=%s status=429 retrying in %.1fs (attempt %d/%d)",
                        self.PROVIDER_NAME,
                        wait,
                        attempt,
                        LLM_RETRY_MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Exhausted retries
                _llm_logger.warning(
                    "LLM rate limit: provider=%s status=429 retries exhausted",
                    self.PROVIDER_NAME,
                )
                raise LLMRateLimitError(
                    "Rate limit hit (429) — retries exhausted"
                ) from None

            # 5xx Server Error — retry with backoff
            if response.status_code in LLM_RETRYABLE_STATUS_CODES:
                if attempt < LLM_RETRY_MAX_ATTEMPTS:
                    wait = LLM_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                    _llm_logger.warning(
                        "LLM server error: provider=%s status=%d retrying in %.1fs (attempt %d/%d)",
                        self.PROVIDER_NAME,
                        response.status_code,
                        wait,
                        attempt,
                        LLM_RETRY_MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Exhausted retries
                _llm_logger.warning(
                    "LLM server error: provider=%s status=%d retries exhausted",
                    self.PROVIDER_NAME,
                    response.status_code,
                )
                raise LLMResponseError(
                    f"Provider returned {response.status_code} after {LLM_RETRY_MAX_ATTEMPTS} attempts: {response.text[:200]}"
                ) from None

            # 4xx Client Error (not 429, not 451) — never retry
            if not response.is_success:
                _llm_logger.warning(
                    "LLM non-success response: provider=%s status=%s",
                    self.PROVIDER_NAME,
                    response.status_code,
                )
                raise LLMResponseError(
                    f"Provider returned {response.status_code}: {response.text[:200]}"
                ) from None

            # Success — parse response
            try:
                data = response.json()
                content = self._parse_response(data)
            except Exception:
                _llm_logger.warning(
                    "LLM parse error: provider=%s",
                    self.PROVIDER_NAME,
                )
                raise LLMResponseError(
                    f"Could not parse response body: {response.text[:200]}"
                ) from None

            _llm_logger.debug(
                "LLM success: provider=%s model=%s",
                self.PROVIDER_NAME,
                self._model,
            )
            return content

        # Unreachable — keeps type-checkers happy
        raise LLMError("Unexpected: retry loop exited without returning or raising")

    async def close(self) -> None:
        """Close the underlying HTTP client and release connection pool."""
        await self._client.aclose()


class OpenAICompatProvider(_BaseHTTPProvider):
    """
    Async provider for OpenAI-compatible endpoints.

    Covers Groq, Ollama, OpenAI, Mistral, Cohere, Together AI,
    and HuggingFace Inference API — all sharing the same
    ``/v1/chat/completions`` call shape.
    """

    PROVIDER_NAME: ClassVar[str] = "OpenAICompatProvider"
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
        super().__init__(api_key, model=model, timeout=timeout)
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _build_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, str], dict[str, object]]:
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
        return url, headers, payload

    def _parse_response(self, data: dict) -> str:
        return data["choices"][0]["message"]["content"]


class AnthropicProvider(_BaseHTTPProvider):
    """
    Async provider for Anthropic's Claude API.

    Uses the ``/v1/messages`` endpoint with the
    ``anthropic-version: 2023-06-01`` header.
    """

    PROVIDER_NAME: ClassVar[str] = "AnthropicProvider"
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
        super().__init__(api_key, model=model, timeout=timeout)
        self._base_url = base_url or self.BASE_URL

    def _build_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, str], dict[str, object]]:
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
        return self._base_url, headers, payload

    def _parse_response(self, data: dict) -> str:
        return data["content"][0]["text"]


class GeminiProvider(_BaseHTTPProvider):
    """
    Async provider for Google Gemini models via the REST API.

    Uses the ``/v1beta/models/{model}:generateContent`` endpoint.
    """

    PROVIDER_NAME: ClassVar[str] = "GeminiProvider"
    BASE_URL: ClassVar[str] = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        timeout: int = 30,
        base_url: str | None = None,
    ) -> None:
        super().__init__(api_key, model=model, timeout=timeout)
        self._base_url = base_url or self.BASE_URL

    def _build_request(
        self,
        prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, dict[str, str], dict[str, object]]:
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
        return url, headers, payload

    def _parse_response(self, data: dict) -> str:
        return data["candidates"][0]["content"]["parts"][0]["text"]


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
    except Exception:
        # Catch generic exceptions (ValueError, TypeError, ConnectionError, etc.)
        # that provider.complete() may raise but aren't LLMError subtypes.
        _llm_logger.warning(
            "LLM unexpected error: provider=%s error=%s",
            type(provider).__name__,
            exc_info=True,
        )
        return "", True
