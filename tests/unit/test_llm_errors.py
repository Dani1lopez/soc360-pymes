from __future__ import annotations

import pytest


class TestLLMErrorHierarchy:
    """Verify LLM error classes exist and follow AppError contract."""

    def test_llm_error_exists_and_inherits_from_app_error(self):
        """LLMError must inherit from AppError for consistent error handling."""
        from app.core.exceptions import AppError, LLMError

        assert issubclass(LLMError, AppError)

    def test_llm_timeout_error_inherits_from_llm_error(self):
        """LLMTimeoutError must be a subclass of LLMError."""
        from app.core.exceptions import LLMError, LLMTimeoutError

        assert issubclass(LLMTimeoutError, LLMError)

    def test_llm_rate_limit_error_inherits_from_llm_error(self):
        """LLMRateLimitError must be a subclass of LLMError."""
        from app.core.exceptions import LLMError, LLMRateLimitError

        assert issubclass(LLMRateLimitError, LLMError)

    def test_llm_content_filter_error_inherits_from_llm_error(self):
        """LLMContentFilterError must be a subclass of LLMError."""
        from app.core.exceptions import LLMError, LLMContentFilterError

        assert issubclass(LLMContentFilterError, LLMError)

    def test_llm_response_error_inherits_from_llm_error(self):
        """LLMResponseError must be a subclass of LLMError."""
        from app.core.exceptions import LLMError, LLMResponseError

        assert issubclass(LLMResponseError, LLMError)

    def test_llm_error_can_be_instantiated_with_detail(self):
        """LLMError must accept detail and status_code like AppError."""
        from app.core.exceptions import LLMError

        err = LLMError(detail="test error", status_code=500)
        assert err.detail == "test error"
        assert err.status_code == 500

    def test_llm_timeout_error_has_default_status_code(self):
        """LLMTimeoutError should default to 408 Request Timeout."""
        from app.core.exceptions import LLMTimeoutError

        err = LLMTimeoutError(detail="timeout")
        assert err.status_code == 408

    def test_llm_rate_limit_error_has_default_status_code(self):
        """LLMRateLimitError should default to 429 Too Many Requests."""
        from app.core.exceptions import LLMRateLimitError

        err = LLMRateLimitError(detail="rate limited")
        assert err.status_code == 429

    def test_llm_content_filter_error_has_default_status_code(self):
        """LLMContentFilterError should default to 451 Unavailable For Legal Reasons."""
        from app.core.exceptions import LLMContentFilterError

        err = LLMContentFilterError(detail="content filtered")
        assert err.status_code == 451

    def test_llm_response_error_has_default_status_code(self):
        """LLMResponseError should default to 502 Bad Gateway."""
        from app.core.exceptions import LLMResponseError

        err = LLMResponseError(detail="bad response")
        assert err.status_code == 502
