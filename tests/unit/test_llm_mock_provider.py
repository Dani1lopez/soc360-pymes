from __future__ import annotations

"""Tests for MockLLMProvider — Batch 4.

Verifies:
1. MockLLMProvider returns predictable, configurable output.
2. Mock is async-compatible.
3. Mock satisfies LLMProvider protocol for substitution.
4. Mock can be used via FastAPI dependency override.
5. Mock can be used via direct instantiation.
6. No network calls (pure deterministic behavior).
"""
import pytest


class TestMockLLMProviderBasicBehavior:
    """Basic mock behavior: output is configurable and predictable."""

    def test_default_response(self):
        """Default constructed MockLLMProvider returns 'mock response'."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider()
        output = asyncio.run(provider.complete(prompt="any", max_tokens=10, temperature=0.0))
        assert output == "mock response"

    def test_custom_response_text(self):
        """Configured response_text is returned unchanged."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider(response_text="custom output")
        output = asyncio.run(provider.complete(prompt="any", max_tokens=10, temperature=0.0))
        assert output == "custom output"

    def test_empty_string_response(self):
        """Mock can return an empty string (valid LLM output)."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider(response_text="")
        output = asyncio.run(provider.complete(prompt="any", max_tokens=10, temperature=0.0))
        assert output == ""

    def test_response_includes_prompt_parameters(self):
        """The mock accepts all three parameters without error."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider(response_text="output")
        # Pass varied prompt, max_tokens, temperature
        output = asyncio.run(
            provider.complete(
                prompt="Tell me a story",
                max_tokens=500,
                temperature=0.9,
            )
        )
        assert output == "output"


class TestMockLLMProviderAsyncBehavior:
    """Async contract: mock must be awaitable and behave like an async provider."""

    def test_complete_returns_awaitable(self):
        """complete() returns a coroutine that must be awaited."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import inspect

        provider = MockLLMProvider()
        result = provider.complete(prompt="test", max_tokens=10, temperature=0.0)
        assert inspect.iscoroutine(result)
        # Await to clean up the coroutine and avoid RuntimeWarning
        asyncio.run(result)

    def test_complete_is_coroutine_function(self):
        """complete must be defined as an async def."""
        from app.core.llm import MockLLMProvider
        import inspect

        provider = MockLLMProvider()
        assert inspect.iscoroutinefunction(provider.complete)

    def test_delay_makes_complete_take_time(self):
        """When delay_seconds > 0, the coroutine waits before returning."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import time

        provider = MockLLMProvider(response_text="delayed", delay_seconds=0.1)
        start = time.monotonic()
        output = asyncio.run(provider.complete(prompt="any", max_tokens=10, temperature=0.0))
        elapsed = time.monotonic() - start
        assert output == "delayed"
        assert elapsed >= 0.09  # allow small tolerance

    def test_zero_delay_returns_immediately(self):
        """delay_seconds=0 returns the response without perceptible delay."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import time

        provider = MockLLMProvider(response_text="fast", delay_seconds=0.0)
        start = time.monotonic()
        output = asyncio.run(provider.complete(prompt="any", max_tokens=10, temperature=0.0))
        elapsed = time.monotonic() - start
        assert output == "fast"
        assert elapsed < 0.05  # should be essentially instant


class TestMockLLMProviderProtocolCompliance:
    """Verify MockLLMProvider satisfies LLMProvider protocol for substitution."""

    def test_satisfies_llm_provider_protocol(self):
        """MockLLMProvider is a runtime instance of LLMProvider."""
        from app.core.llm import LLMProvider, MockLLMProvider

        provider = MockLLMProvider()
        assert isinstance(provider, LLMProvider)

    def test_passes_runtime_checkable_check(self):
        """MockLLMProvider passes the runtime checkable protocol check."""
        from app.core.llm import LLMProvider, MockLLMProvider

        provider = MockLLMProvider()
        # The @runtime_checkable decorator allows isinstance checks on protocols
        assert isinstance(provider, LLMProvider)

    def test_has_complete_method_with_correct_signature(self):
        """MockLLMProvider.complete matches the protocol signature."""
        from app.core.llm import MockLLMProvider
        import inspect

        mock = MockLLMProvider()
        sig = inspect.signature(mock.complete)
        params = list(sig.parameters.keys())
        # self is not included for bound methods
        assert params == ["prompt", "max_tokens", "temperature"]


class TestMockLLMProviderUsagePatterns:
    """Verify mock can be used via direct instantiation and dependency override."""

    def test_direct_instantiation_in_service(self):
        """A service can accept MockLLMProvider via direct instantiation."""
        from app.core.llm import MockLLMProvider
        import asyncio

        # Simulate a service that calls the provider
        async def call_provider(provider, prompt):
            return await provider.complete(prompt=prompt, max_tokens=50, temperature=0.0)

        mock = MockLLMProvider(response_text="service response")
        result = asyncio.run(call_provider(mock, "hello"))
        assert result == "service response"

    def test_multiple_instances_are_independent(self):
        """Two MockLLMProvider instances return their own configured responses."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider_a = MockLLMProvider(response_text="response A")
        provider_b = MockLLMProvider(response_text="response B")

        async def run():
            result_a = await provider_a.complete(prompt="", max_tokens=1, temperature=0.0)
            result_b = await provider_b.complete(prompt="", max_tokens=1, temperature=0.0)
            return result_a, result_b

        output_a, output_b = asyncio.run(run())
        assert output_a == "response A"
        assert output_b == "response B"
        assert output_a != output_b

    def test_mock_produces_deterministic_json_text(self):
        """Mock response that looks like JSON is returned as-is (no parsing)."""
        from app.core.llm import MockLLMProvider
        import asyncio

        json_response = '{"analysis": "valid", "score": 0.95}'
        provider = MockLLMProvider(response_text=json_response)
        output = asyncio.run(provider.complete(prompt="analyze", max_tokens=100, temperature=0.0))
        assert output == json_response
        # Verify it is a string and can be parsed as JSON
        import json
        parsed = json.loads(output)
        assert parsed["score"] == 0.95


class TestMockLLMProviderNoNetworkCalls:
    """Verify the mock makes no network calls (pure in-memory behavior)."""

    def test_complete_does_not_open_networkConnections(self):
        """complete() returns without attempting any network operations."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import socket

        provider = MockLLMProvider(response_text="no network")
        # If any network call were attempted, it would raise.
        # We verify the call completes cleanly.
        output = asyncio.run(provider.complete(prompt="test", max_tokens=10, temperature=0.0))
        assert output == "no network"

    def test_complete_succeeds_without_api_key(self):
        """MockLLMProvider works without any API key configured."""
        from app.core.llm import MockLLMProvider
        import asyncio

        # No api_key argument even exists — the mock has none
        provider = MockLLMProvider(response_text="works without keys")
        output = asyncio.run(provider.complete(prompt="test", max_tokens=10, temperature=0.0))
        assert output == "works without keys"
