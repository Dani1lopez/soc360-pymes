from __future__ import annotations

"""Tests for FastAPI dependency wiring for LLM providers.

These tests verify that:
1. get_llm dependency can be imported and used as a FastAPI dependency
2. The dependency returns an instance that satisfies LLMProvider protocol
"""
import pytest


class TestGetLlmDependency:
    """Verify get_llm dependency wiring in app/dependencies."""

    def test_get_llm_is_importable(self):
        """get_llm must be importable from app.dependencies."""
        from app.dependencies import get_llm

        assert get_llm is not None

    def test_get_llm_is_an_async_callable(self):
        """get_llm must be an async callable suitable for FastAPI dependency injection."""
        import inspect
        from app.dependencies import get_llm

        assert inspect.iscoroutinefunction(get_llm)

    def test_get_llm_returns_llm_provider_instance(self):
        """get_llm() must return an object satisfying LLMProvider protocol."""
        import asyncio
        from app.dependencies import get_llm
        from app.core.llm import LLMProvider

        async def _run():
            provider = await get_llm()
            return provider

        provider = asyncio.run(_run())
        from app.core.llm import LLMProvider

        assert isinstance(provider, LLMProvider)

    def test_get_llm_returns_singleton_instance(self):
        """Two calls to get_llm() must return the same cached instance."""
        import asyncio
        from app.dependencies import get_llm

        async def _run():
            p1 = await get_llm()
            p2 = await get_llm()
            return p1, p2

        p1, p2 = asyncio.run(_run())
        assert p1 is p2
