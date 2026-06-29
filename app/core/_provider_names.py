"""Provider names recognized by the LLM subsystem.

Imported by both config.py (LLM_PROVIDER validator) and llm.py
(registry validation). Exists to break circular import —
config.py cannot import from llm.py during Settings construction.

IMPORTANT: When adding a new provider, this frozenset MUST be updated
alongside _PROVIDER_REGISTRY in llm.py. An assertion in _register_providers()
catches mismatches at import time.
"""

_PROVIDER_NAMES: frozenset[str] = frozenset({
    "groq", "ollama", "openai", "anthropic",
    "gemini", "mistral", "cohere", "together", "huggingface",
})
