from __future__ import annotations

# Disable session-scoped database setup for unit tests that don't need it.
# The tests/unit/conftest.py overrides the session-level prepare_database
# with an empty fixture so LLM-only unit tests run without a database.
from typing import AsyncGenerator

import pytest


@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    """Override tests/conftest.py prepare_database — no-op for unit tests."""
    pass


@pytest.fixture
def mock_llm_provider():
    """Return a MockLLMProvider configured with test output.

    Usage in unit tests that need an LLM provider without network calls:

        async def test_something(mock_llm_provider):
            result = await mock_llm_provider.complete(
                prompt="analyze this",
                max_tokens=100,
                temperature=0.0,
            )
            assert result == "test mock response"

    For FastAPI dependency override, use:

        app.dependency_overrides[get_llm_provider] = lambda: mock_llm_provider
    """
    from app.core.llm import MockLLMProvider

    return MockLLMProvider(response_text="test mock response", delay_seconds=0.0)
