"""LLM provider dependency: singleton factory."""
from __future__ import annotations

from app.core.llm import LLMProvider, get_llm_provider


async def get_llm() -> LLMProvider:
    """FastAPI dependency: return the singleton LLM provider for this request."""
    return get_llm_provider()
