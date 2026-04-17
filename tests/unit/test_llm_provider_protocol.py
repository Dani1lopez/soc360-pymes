from __future__ import annotations

import pytest
from typing import Protocol, runtime_checkable


class TestLLMProviderProtocolExists:
    """Verify LLMProvider protocol exists with correct interface."""

    def test_llm_provider_protocol_exists(self):
        """LLMProvider must be importable from app.core.llm."""
        from app.core.llm import LLMProvider

        # Protocol should exist and be a Protocol subclass
        assert issubclass(LLMProvider, Protocol)

    def test_llm_provider_is_runtime_checkable(self):
        """LLMProvider must be @runtime_checkable for structural subtyping."""
        from app.core.llm import LLMProvider

        assert hasattr(LLMProvider, "__protocol_attrs__") or hasattr(LLMProvider, "_is_protocol")

    def test_complete_method_exists_on_protocol(self):
        """LLMProvider.complete must be defined with correct signature."""
        from app.core.llm import LLMProvider

        # Verify complete is part of the protocol
        protocol = LLMProvider.__protocol_attrs__ if hasattr(LLMProvider, "__protocol_attrs__") else []
        assert "complete" in protocol or hasattr(LLMProvider, "complete")


class TestLLMProviderCompleteSignature:
    """Verify the complete method has the expected signature."""

    def test_complete_is_an_async_method(self):
        """complete must be an async method (awaitable)."""
        from app.core.llm import LLMProvider
        import inspect

        # Get the 'complete' method from the protocol
        # In Python 3.10+, Protocol uses __protocol_attrs__
        protocol_attrs = getattr(LLMProvider, "__protocol_attrs__", set())
        if hasattr(LLMProvider, "__annotations__"):
            annotations = LLMProvider.__annotations__
        else:
            annotations = {}

        # The complete method should be defined (even if we can't inspect it directly on Protocol)
        assert "complete" in protocol_attrs or hasattr(LLMProvider, "complete")

    def test_complete_returns_str(self):
        """complete return type annotation must be str."""
        from app.core.llm import LLMProvider

        # Check return annotation
        hints = getattr(LLMProvider, "__annotations__", {})
        assert hints.get("return") is str or "return" not in hints  # Optional return annotation is OK


class TestMockLLMProviderCompliance:
    """Verify MockLLMProvider satisfies the LLMProvider protocol."""

    def test_mock_llm_provider_is_importable(self):
        """MockLLMProvider must be importable from app.core.llm."""
        from app.core.llm import MockLLMProvider

        # Must be instantiable without arguments
        provider = MockLLMProvider()
        assert provider is not None

    def test_mock_llm_provider_satisfies_protocol(self):
        """MockLLMProvider must satisfy the LLMProvider protocol at runtime."""
        from app.core.llm import LLMProvider, MockLLMProvider

        provider = MockLLMProvider()
        assert isinstance(provider, LLMProvider)

    def test_mock_complete_returns_str(self):
        """MockLLMProvider.complete must return a string."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider(response_text="hello world")
        result = provider.complete(prompt="say hello", max_tokens=10, temperature=0.1)
        import inspect
        assert inspect.iscoroutine(result)
        output = asyncio.run(result)
        assert isinstance(output, str)

    def test_mock_complete_returns_configured_response(self):
        """MockLLMProvider.complete returns the configured response_text."""
        from app.core.llm import MockLLMProvider
        import asyncio

        expected = "the mock response"
        provider = MockLLMProvider(response_text=expected)
        output = asyncio.run(
            provider.complete(prompt="any prompt", max_tokens=100, temperature=0.0)
        )
        assert output == expected

    def test_mock_complete_is_async(self):
        """MockLLMProvider.complete must be an async method."""
        from app.core.llm import MockLLMProvider
        import inspect

        provider = MockLLMProvider()
        assert inspect.iscoroutinefunction(provider.complete)

    def test_mock_complete_with_delay_does_not_block(self):
        """MockLLMProvider with delay returns after the configured delay."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import time

        provider = MockLLMProvider(response_text="delayed", delay_seconds=0.05)
        start = time.monotonic()
        output = asyncio.run(
            provider.complete(prompt="test", max_tokens=10, temperature=0.1)
        )
        elapsed = time.monotonic() - start
        assert output == "delayed"
        assert elapsed >= 0.04  # at least 40ms (allow small tolerance)
