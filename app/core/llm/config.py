"""LLM configuration constants and credential redaction."""
from __future__ import annotations

import re

from app.core.logging import get_logger

_llm_logger = get_logger("app.core.llm")

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


LLM_RETRY_MAX_ATTEMPTS: int = 3
LLM_RETRY_BACKOFF_BASE_SECONDS: float = 1.0
LLM_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
