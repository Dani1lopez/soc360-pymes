from __future__ import annotations

"""Tests for LLM provider factory and singleton behavior.

These tests verify that:
1. Factory returns the correct provider class for each supported provider name
2. Provider instances are cached (singleton pattern) within a process
3. Unknown provider names raise LLMResponseError with a safe (no key) message
"""
import pytest


class TestProviderFactorySelection:
    """Verify factory maps provider names to correct provider classes."""

    def test_factory_returns_openai_compat_for_groq(self):
        """groq → OpenAICompatProvider."""
        from app.core.llm import get_llm_provider, _create_provider

        provider = _create_provider("groq")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_ollama(self):
        """ollama → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("ollama")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_openai(self):
        """openai → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("openai")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_mistral(self):
        """mistral → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("mistral")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_cohere(self):
        """cohere → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("cohere")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_together(self):
        """together → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("together")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_openai_compat_for_huggingface(self):
        """huggingface → OpenAICompatProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("huggingface")
        from app.core.llm import OpenAICompatProvider

        assert isinstance(provider, OpenAICompatProvider)

    def test_factory_returns_anthropic_provider(self):
        """anthropic → AnthropicProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("anthropic")
        from app.core.llm import AnthropicProvider

        assert isinstance(provider, AnthropicProvider)

    def test_factory_returns_gemini_provider(self):
        """gemini → GeminiProvider."""
        from app.core.llm import _create_provider

        provider = _create_provider("gemini")
        from app.core.llm import GeminiProvider

        assert isinstance(provider, GeminiProvider)

    def test_factory_raises_on_unknown_provider(self):
        """Unknown provider name raises LLMResponseError."""
        from app.core.llm import _create_provider
        from app.core.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError) as exc_info:
            _create_provider("unknown-provider")

        # Must NOT contain any API key
        detail = str(exc_info.value.detail)
        assert "gsk_" not in detail
        assert "sk-" not in detail
        assert "api_key" not in detail.lower()


class TestProviderSingletonCache:
    """Verify singleton cache: same provider name returns same instance."""

    def test_singleton_returns_same_instance(self):
        """Two calls with same provider name return the same object."""
        from app.core.llm import get_llm_provider

        provider1 = get_llm_provider()
        provider2 = get_llm_provider()

        assert provider1 is provider2

    def test_singleton_caches_by_provider_name(self, monkeypatch):
        """Different provider names return different cached instances (no cross-contamination).

        Proves the singleton cache is keyed by provider name, not a single global
        instance shared across all provider names.
        """
        from app.core.llm import get_llm_provider, _llm_singletons
        from app.core.llm import OpenAICompatProvider, AnthropicProvider

        # Isolate: start from a clean cache slate for this test
        _llm_singletons.clear()

        # First call: LLM_PROVIDER="groq" → OpenAICompatProvider
        monkeypatch.setattr("app.core.llm.settings.LLM_PROVIDER", "groq")
        provider_a = get_llm_provider()
        assert isinstance(provider_a, OpenAICompatProvider)

        # Second call with SAME provider name → same object (cached)
        provider_a2 = get_llm_provider()
        assert provider_a is provider_a2, "Same provider name must return the same cached instance"

        # Third call: LLM_PROVIDER="anthropic" → different singleton slot
        monkeypatch.setattr("app.core.llm.settings.LLM_PROVIDER", "anthropic")
        provider_b = get_llm_provider()
        assert isinstance(provider_b, AnthropicProvider)

        # The two provider names must NOT be the same object (proves per-name cache)
        assert provider_a is not provider_b, (
            "Different provider names must return different cached instances; "
            "a global singleton would make them identical"
        )


class TestFactoryUsesCorrectConfig:
    """Verify factory reads settings to build providers."""

    def test_factory_uses_settings_llm_timeout(self):
        """Provider timeout is taken from LLM_TIMEOUT setting."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("groq")

        assert provider._timeout == settings.LLM_TIMEOUT

    def test_factory_uses_settings_llm_max_tokens(self):
        """Provider model is taken from per-provider model setting (groq uses GROQ_MODEL)."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("groq")

        assert provider._model == settings.GROQ_MODEL

    def test_factory_uses_groq_api_key(self):
        """Provider api_key is taken from per-provider key setting."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("groq")

        assert provider._api_key == settings.GROQ_API_KEY


class TestOllamaProviderConfig:
    """Verify ollama provider is wired with correct Ollama-specific settings."""

    def test_ollama_provider_uses_ollama_base_url(self):
        """Ollama provider must use settings.OLLAMA_URL, NOT the OpenAI default."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("ollama")

        # Must use the Ollama URL, not api.openai.com
        assert provider._base_url == settings.OLLAMA_URL
        assert provider._base_url == "http://localhost:11434"

    def test_ollama_provider_does_not_use_openai_base_url(self):
        """Ollama provider must NOT inherit https://api.openai.com/v1 as base_url."""
        from app.core.llm import _create_provider

        provider = _create_provider("ollama")

        # The bug would set this to the OpenAI default
        assert provider._base_url != "https://api.openai.com/v1"

    def test_ollama_provider_uses_ollama_model(self):
        """Ollama provider model is taken from settings.OLLAMA_MODEL."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("ollama")

        assert provider._model == settings.OLLAMA_MODEL

    def test_ollama_provider_uses_empty_api_key(self):
        """Ollama has no auth — api_key must be empty string."""
        from app.core.llm import _create_provider

        provider = _create_provider("ollama")

        assert provider._api_key == ""

    def test_ollama_provider_uses_llm_timeout(self):
        """Ollama provider timeout is taken from settings.LLM_TIMEOUT."""
        from app.core.llm import _create_provider
        from app.core.config import settings

        provider = _create_provider("ollama")

        assert provider._timeout == settings.LLM_TIMEOUT


class TestGetLlmProviderDependency:
    """Verify get_llm_provider works as a FastAPI dependency."""

    def test_get_llm_provider_returns_provider_instance(self):
        """get_llm_provider() must return an object satisfying LLMProvider protocol."""
        from app.core.llm import get_llm_provider, LLMProvider

        provider = get_llm_provider()

        assert isinstance(provider, LLMProvider)

    def test_get_llm_provider_is_callable(self):
        """get_llm_provider must be importable and callable."""
        from app.core.llm import get_llm_provider

        assert callable(get_llm_provider)
