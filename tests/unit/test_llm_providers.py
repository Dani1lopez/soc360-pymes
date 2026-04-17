from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestOpenAICompatProviderExists:
    """Verify OpenAICompatProvider exists and satisfies LLMProvider."""

    def test_openai_compat_provider_is_importable(self):
        """OpenAICompatProvider must be importable from app.core.llm."""
        from app.core.llm import OpenAICompatProvider

        assert OpenAICompatProvider is not None

    def test_openai_compat_provider_inherits_from_object(self):
        """OpenAICompatProvider should be a class (not aProtocol)."""
        from app.core.llm import OpenAICompatProvider

        assert isinstance(OpenAICompatProvider, type)

    def test_complete_method_is_async(self):
        """complete must be an async method."""
        import inspect
        from app.core.llm import OpenAICompatProvider

        assert inspect.iscoroutinefunction(OpenAICompatProvider.complete)


class TestOpenAICompatProviderInit:
    """Verify OpenAICompatProvider accepts required config."""

    def test_init_requires_api_key(self):
        """OpenAICompatProvider.__init__ must require api_key."""
        from app.core.llm import OpenAICompatProvider
        import inspect

        sig = inspect.signature(OpenAICompatProvider.__init__)
        params = list(sig.parameters.keys())
        assert "api_key" in params

    def test_init_accepts_base_url(self):
        """OpenAICompatProvider.__init__ must accept base_url for custom endpoints."""
        from app.core.llm import OpenAICompatProvider
        import inspect

        sig = inspect.signature(OpenAICompatProvider.__init__)
        params = list(sig.parameters.keys())
        assert "base_url" in params

    def test_init_accepts_model(self):
        """OpenAICompatProvider.__init__ must accept model name."""
        from app.core.llm import OpenAICompatProvider
        import inspect

        sig = inspect.signature(OpenAICompatProvider.__init__)
        params = list(sig.parameters.keys())
        assert "model" in params

    def test_init_accepts_timeout(self):
        """OpenAICompatProvider.__init__ must accept timeout."""
        from app.core.llm import OpenAICompatProvider
        import inspect

        sig = inspect.signature(OpenAICompatProvider.__init__)
        params = list(sig.parameters.keys())
        assert "timeout" in params


class TestOpenAICompatProviderComplete:
    """Verify complete() behavior via httpx mocking."""

    @pytest.mark.asyncio
    async def test_complete_returns_str(self):
        """complete() must return a string."""
        from app.core.llm import OpenAICompatProvider

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello world"}}]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Say hello", max_tokens=10, temperature=0.1)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_complete_returns_raw_text(self):
        """complete() must return raw text without JSON parsing."""
        from app.core.llm import OpenAICompatProvider

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        raw_content = "The vulnerabilities found are..."
        mock_response.json.return_value = {
            "choices": [{"message": {"content": raw_content}}]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Test prompt", max_tokens=100, temperature=0.5)
            assert result == raw_content

    @pytest.mark.asyncio
    async def test_complete_raises_llm_error_on_http_error(self):
        """HTTP errors must raise LLMError subclasses."""
        from app.core.llm import OpenAICompatProvider
        from app.core.exceptions import LLMResponseError

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.is_success = False
        mock_response.text = "Internal server error"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMResponseError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_raises_timeout_on_timeout(self):
        """Timeout must raise LLMTimeoutError."""
        from app.core.llm import OpenAICompatProvider
        from app.core.exceptions import LLMTimeoutError
        import httpx

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.TimeoutException("timed out")
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMTimeoutError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_raises_rate_limit_on_429(self):
        """HTTP 429 must raise LLMRateLimitError."""
        from app.core.llm import OpenAICompatProvider
        from app.core.exceptions import LLMRateLimitError

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.is_success = False
        mock_response.text = "Rate limit exceeded"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMRateLimitError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_includes_request_body(self):
        """complete() must send correct JSON body to the endpoint."""
        from app.core.llm import OpenAICompatProvider

        provider = OpenAICompatProvider(api_key="test-key", model="test-model")
        recorded_payload = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "response"}}]
        }

        async def mock_post(url, json=None, headers=None, timeout=None):
            recorded_payload["url"] = url
            recorded_payload["headers"] = headers
            recorded_payload["json"] = json
            recorded_payload["timeout"] = timeout
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = mock_post
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            await provider.complete("Say hello", max_tokens=20, temperature=0.3)

        assert recorded_payload["url"] == "https://api.openai.com/v1/chat/completions"
        assert recorded_payload["headers"]["Authorization"] == "Bearer test-key"
        assert recorded_payload["json"]["model"] == "test-model"
        assert recorded_payload["json"]["messages"] == [{"role": "user", "content": "Say hello"}]
        assert recorded_payload["json"]["max_tokens"] == 20
        assert recorded_payload["json"]["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_complete_uses_custom_base_url(self):
        """base_url must override the default OpenAI endpoint."""
        from app.core.llm import OpenAICompatProvider

        provider = OpenAICompatProvider(
            api_key="test-key",
            model="test-model",
            base_url="https://api.groq.com/v1",
        )
        recorded_url = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "response"}}]
        }

        async def mock_post(url, json=None, headers=None, timeout=None):
            recorded_url["url"] = url
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = mock_post
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            await provider.complete("Test", max_tokens=10, temperature=0.1)

        assert recorded_url["url"] == "https://api.groq.com/v1/chat/completions"


class TestAnthropicProviderExists:
    """Verify AnthropicProvider exists."""

    def test_anthropic_provider_is_importable(self):
        """AnthropicProvider must be importable from app.core.llm."""
        from app.core.llm import AnthropicProvider

        assert AnthropicProvider is not None

    def test_complete_method_is_async(self):
        """complete must be an async method."""
        import inspect
        from app.core.llm import AnthropicProvider

        assert inspect.iscoroutinefunction(AnthropicProvider.complete)


class TestAnthropicProviderInit:
    """Verify AnthropicProvider.__init__ signature."""

    def test_init_requires_api_key(self):
        """AnthropicProvider.__init__ must require api_key."""
        from app.core.llm import AnthropicProvider
        import inspect

        sig = inspect.signature(AnthropicProvider.__init__)
        params = list(sig.parameters.keys())
        assert "api_key" in params

    def test_init_accepts_model(self):
        """AnthropicProvider.__init__ must accept model name."""
        from app.core.llm import AnthropicProvider
        import inspect

        sig = inspect.signature(AnthropicProvider.__init__)
        params = list(sig.parameters.keys())
        assert "model" in params

    def test_init_accepts_timeout(self):
        """AnthropicProvider.__init__ must accept timeout."""
        from app.core.llm import AnthropicProvider
        import inspect

        sig = inspect.signature(AnthropicProvider.__init__)
        params = list(sig.parameters.keys())
        assert "timeout" in params


class TestAnthropicProviderComplete:
    """Verify complete() behavior."""

    @pytest.mark.asyncio
    async def test_complete_returns_str(self):
        """complete() must return a string."""
        from app.core.llm import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "content": [{"text": "Hello world"}]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Say hello", max_tokens=10, temperature=0.1)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_complete_returns_raw_text(self):
        """complete() must return the raw text from content block."""
        from app.core.llm import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key", model="test-model")
        raw_content = "The vulnerabilities found are..."
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "content": [{"text": raw_content}]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Test prompt", max_tokens=100, temperature=0.5)
            assert result == raw_content

    @pytest.mark.asyncio
    async def test_complete_raises_timeout_on_timeout(self):
        """Timeout must raise LLMTimeoutError."""
        from app.core.llm import AnthropicProvider
        from app.core.exceptions import LLMTimeoutError
        import httpx

        provider = AnthropicProvider(api_key="test-key", model="test-model")

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.TimeoutException("timed out")
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMTimeoutError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_raises_rate_limit_on_429(self):
        """HTTP 429 must raise LLMRateLimitError."""
        from app.core.llm import AnthropicProvider
        from app.core.exceptions import LLMRateLimitError

        provider = AnthropicProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.is_success = False
        mock_response.text = "Rate limit exceeded"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMRateLimitError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_sends_correct_payload(self):
        """complete() must send correct JSON body to Anthropic endpoint."""
        from app.core.llm import AnthropicProvider

        provider = AnthropicProvider(api_key="test-key", model="test-model")
        recorded_payload = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "content": [{"text": "response"}]
        }

        async def mock_post(url, json=None, headers=None, timeout=None):
            recorded_payload["url"] = url
            recorded_payload["headers"] = headers
            recorded_payload["json"] = json
            recorded_payload["timeout"] = timeout
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = mock_post
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            await provider.complete("Say hello", max_tokens=20, temperature=0.3)

        assert recorded_payload["url"] == "https://api.anthropic.com/v1/messages"
        assert recorded_payload["headers"]["x-api-key"] == "test-key"
        assert recorded_payload["headers"]["anthropic-version"] == "2023-06-01"
        assert recorded_payload["json"]["model"] == "test-model"
        assert recorded_payload["json"]["messages"] == [{"role": "user", "content": "Say hello"}]
        assert recorded_payload["json"]["max_tokens"] == 20
        assert recorded_payload["json"]["temperature"] == 0.3


class TestGeminiProviderExists:
    """Verify GeminiProvider exists."""

    def test_gemini_provider_is_importable(self):
        """GeminiProvider must be importable from app.core.llm."""
        from app.core.llm import GeminiProvider

        assert GeminiProvider is not None

    def test_complete_method_is_async(self):
        """complete must be an async method."""
        import inspect
        from app.core.llm import GeminiProvider

        assert inspect.iscoroutinefunction(GeminiProvider.complete)


class TestGeminiProviderInit:
    """Verify GeminiProvider.__init__ signature."""

    def test_init_requires_api_key(self):
        """GeminiProvider.__init__ must require api_key."""
        from app.core.llm import GeminiProvider
        import inspect

        sig = inspect.signature(GeminiProvider.__init__)
        params = list(sig.parameters.keys())
        assert "api_key" in params

    def test_init_accepts_model(self):
        """GeminiProvider.__init__ must accept model name."""
        from app.core.llm import GeminiProvider
        import inspect

        sig = inspect.signature(GeminiProvider.__init__)
        params = list(sig.parameters.keys())
        assert "model" in params

    def test_init_accepts_timeout(self):
        """GeminiProvider.__init__ must accept timeout."""
        from app.core.llm import GeminiProvider
        import inspect

        sig = inspect.signature(GeminiProvider.__init__)
        params = list(sig.parameters.keys())
        assert "timeout" in params


class TestGeminiProviderComplete:
    """Verify complete() behavior."""

    @pytest.mark.asyncio
    async def test_complete_returns_str(self):
        """complete() must return a string."""
        from app.core.llm import GeminiProvider

        provider = GeminiProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Hello world"}]
                }
            }]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Say hello", max_tokens=10, temperature=0.1)
            assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_complete_returns_raw_text(self):
        """complete() must return raw text from candidates."""
        from app.core.llm import GeminiProvider

        provider = GeminiProvider(api_key="test-key", model="test-model")
        raw_content = "The vulnerabilities found are..."
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": raw_content}]
                }
            }]
        }

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            result = await provider.complete("Test prompt", max_tokens=100, temperature=0.5)
            assert result == raw_content

    @pytest.mark.asyncio
    async def test_complete_raises_timeout_on_timeout(self):
        """Timeout must raise LLMTimeoutError."""
        from app.core.llm import GeminiProvider
        from app.core.exceptions import LLMTimeoutError
        import httpx

        provider = GeminiProvider(api_key="test-key", model="test-model")

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.TimeoutException("timed out")
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMTimeoutError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_raises_rate_limit_on_429(self):
        """HTTP 429 must raise LLMRateLimitError."""
        from app.core.llm import GeminiProvider
        from app.core.exceptions import LLMRateLimitError

        provider = GeminiProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.is_success = False
        mock_response.text = "Rate limit exceeded"

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            with pytest.raises(LLMRateLimitError):
                await provider.complete("Test", max_tokens=10, temperature=0.1)

    @pytest.mark.asyncio
    async def test_complete_sends_correct_payload(self):
        """complete() must send correct JSON body to Gemini endpoint."""
        from app.core.llm import GeminiProvider

        provider = GeminiProvider(api_key="test-key", model="test-model")
        recorded_payload = {}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "response"}]
                }
            }]
        }

        async def mock_post(url, json=None, headers=None, timeout=None):
            recorded_payload["url"] = url
            recorded_payload["headers"] = headers
            recorded_payload["json"] = json
            recorded_payload["timeout"] = timeout
            return mock_response

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = mock_post
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.__aexit__.return_value = None
            MockClient.return_value = mock_instance

            await provider.complete("Say hello", max_tokens=20, temperature=0.3)

        assert recorded_payload["url"] == "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
        assert recorded_payload["headers"]["x-goog-api-key"] == "test-key"
        assert recorded_payload["json"]["contents"] == [{"parts": [{"text": "Say hello"}]}]
        assert recorded_payload["json"]["generationConfig"]["maxOutputTokens"] == 20
        assert recorded_payload["json"]["generationConfig"]["temperature"] == 0.3


class TestOpenAICompatProvider451:
    """Verify HTTP 451 content-filter path logs and raises in a single clear branch."""

    @pytest.mark.asyncio
    async def test_451_logs_before_raising(self):
        """451 must log a warning BEFORE raising LLMContentFilterError."""
        import logging
        from app.core.llm import OpenAICompatProvider
        from app.core.exceptions import LLMContentFilterError

        provider = OpenAICompatProvider(
            api_key="test-key",
            model="test-model",
            base_url="https://api.example.com/v1",
        )
        mock_response = MagicMock()
        mock_response.status_code = 451
        mock_response.is_success = False
        mock_response.text = "Content not available"

        log_records: list[logging.LogRecord] = []

        class LogCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = LogCapture()
        handler.setLevel(logging.DEBUG)
        llm_logger = logging.getLogger("app.core.llm")
        original_level = llm_logger.level
        llm_logger.setLevel(logging.DEBUG)
        llm_logger.addHandler(handler)

        try:
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                MockClient.return_value = mock_instance

                with pytest.raises(LLMContentFilterError):
                    await provider.complete("test", max_tokens=10, temperature=0.1)

            # A warning must have been logged before the exception
            warning_logs = [r for r in log_records if r.levelno >= logging.WARNING]
            assert any("451" in r.getMessage() or "content filtered" in r.getMessage().lower() for r in warning_logs), (
                f"Expected a warning log mentioning '451' or 'content filtered', got: {[r.getMessage() for r in log_records]}"
            )
        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)


class TestAnthropicProvider451:
    """Verify HTTP 451 content-filter path logs and raises in a single clear branch."""

    @pytest.mark.asyncio
    async def test_451_logs_before_raising(self):
        """451 must log a warning BEFORE raising LLMContentFilterError."""
        import logging
        from app.core.llm import AnthropicProvider
        from app.core.exceptions import LLMContentFilterError

        provider = AnthropicProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 451
        mock_response.is_success = False
        mock_response.text = "Content not available"

        log_records: list[logging.LogRecord] = []

        class LogCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = LogCapture()
        handler.setLevel(logging.DEBUG)
        llm_logger = logging.getLogger("app.core.llm")
        original_level = llm_logger.level
        llm_logger.setLevel(logging.DEBUG)
        llm_logger.addHandler(handler)

        try:
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                MockClient.return_value = mock_instance

                with pytest.raises(LLMContentFilterError):
                    await provider.complete("test", max_tokens=10, temperature=0.1)

            warning_logs = [r for r in log_records if r.levelno >= logging.WARNING]
            assert any("451" in r.getMessage() or "content filtered" in r.getMessage().lower() for r in warning_logs), (
                f"Expected a warning log mentioning '451' or 'content filtered', got: {[r.getMessage() for r in log_records]}"
            )
        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)


class TestGeminiProvider451:
    """Verify HTTP 451 content-filter path logs and raises in a single clear branch."""

    @pytest.mark.asyncio
    async def test_451_logs_before_raising(self):
        """451 must log a warning BEFORE raising LLMContentFilterError."""
        import logging
        from app.core.llm import GeminiProvider
        from app.core.exceptions import LLMContentFilterError

        provider = GeminiProvider(api_key="test-key", model="test-model")
        mock_response = MagicMock()
        mock_response.status_code = 451
        mock_response.is_success = False
        mock_response.text = "Content not available"

        log_records: list[logging.LogRecord] = []

        class LogCapture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(record)

        handler = LogCapture()
        handler.setLevel(logging.DEBUG)
        llm_logger = logging.getLogger("app.core.llm")
        original_level = llm_logger.level
        llm_logger.setLevel(logging.DEBUG)
        llm_logger.addHandler(handler)

        try:
            with patch("httpx.AsyncClient") as MockClient:
                mock_instance = AsyncMock()
                mock_instance.post.return_value = mock_response
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.__aexit__.return_value = None
                MockClient.return_value = mock_instance

                with pytest.raises(LLMContentFilterError):
                    await provider.complete("test", max_tokens=10, temperature=0.1)

            warning_logs = [r for r in log_records if r.levelno >= logging.WARNING]
            assert any("451" in r.getMessage() or "content filtered" in r.getMessage().lower() for r in warning_logs), (
                f"Expected a warning log mentioning '451' or 'content filtered', got: {[r.getMessage() for r in log_records]}"
            )
        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)
