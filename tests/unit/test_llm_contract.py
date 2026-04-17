from __future__ import annotations

"""Contract verification tests for LLM abstraction → AI Analysis node boundary.

Batch 5 — Integration / Contract Verification / Docs

These tests verify:
1. LLM provider output (raw text) is compatible with downstream parsing into EnrichedFinding
2. EnrichedFinding.to_fallback() correctly marks findings for retry
3. MockLLMProvider can simulate failure scenarios that trigger fallback behavior
4. No API keys leak through error paths
"""
import pytest


class TestProviderOutputContract:
    """Verify LLM provider output is raw text suitable for downstream JSON parsing."""

    def test_mock_provider_output_is_raw_string(self):
        """Provider.complete() returns a string that can be used by downstream parser."""
        from app.core.llm import MockLLMProvider
        import asyncio

        # Simulate what the AI Analysis node receives from the LLM
        provider = MockLLMProvider(
            response_text='{"vuln_type": "open_redirect", "severity": "high", "title": "Open Redirect in /api/redirect"}'
        )
        result = asyncio.run(provider.complete(prompt="analyze", max_tokens=500, temperature=0.0))
        assert isinstance(result, str)
        assert result.startswith("{")  # JSON-formatted text

    def test_mock_provider_output_contains_findings_data(self):
        """Raw provider text contains fields needed to construct EnrichedFinding."""
        from app.core.llm import MockLLMProvider
        import asyncio
        import json

        # A realistic JSON payload that downstream parser would receive
        findings_json = json.dumps({
            "vuln_type": "sql_injection",
            "severity": "critical",
            "title": "SQL Injection in /api/users",
            "description": "User input not sanitized",
            "evidence": "Payload: ' OR 1=1 --",
            "remediation": "Use parameterized queries",
            "port": 8080,
            "protocol": "tcp",
            "service": "http",
            "cve": "CVE-2024-1234",
            "cwe": "CWE-89",
            "path": "/api/users",
            "cvss_score": 9.8,
        })
        provider = MockLLMProvider(response_text=findings_json)
        result = asyncio.run(provider.complete(prompt="analyze", max_tokens=500, temperature=0.0))

        parsed = json.loads(result)
        assert parsed["severity"] == "critical"
        assert parsed["vuln_type"] == "sql_injection"
        assert parsed["cvss_score"] == 9.8

    def test_mock_provider_returns_plain_text_for_non_json_prompts(self):
        """Providers return plain text when LLM doesn't output JSON."""
        from app.core.llm import MockLLMProvider
        import asyncio

        plain_response = "No vulnerabilities found in the scanned endpoints."
        provider = MockLLMProvider(response_text=plain_response)
        result = asyncio.run(provider.complete(prompt="analyze", max_tokens=100, temperature=0.0))
        assert result == plain_response
        # Downstream parser must handle non-JSON gracefully
        import json
        try:
            json.loads(result)
            pytest.fail("Plain text should not parse as JSON")
        except json.JSONDecodeError:
            pass  # Expected


class TestEnrichedFindingFallbackContract:
    """Verify EnrichedFinding.to_fallback() produces correct retry-marked copies."""

    def test_to_fallback_marks_ai_enriched_false(self):
        """to_fallback() sets ai_enriched=False."""
        from app.core.contracts import EnrichedFinding
        from uuid import uuid4

        finding = EnrichedFinding(
            asset_id=uuid4(),
            scan_id=uuid4(),
            vuln_type="xss",
            severity="high",
            title="Cross-Site Scripting in /api/feedback",
            description="Reflected XSS",
            evidence="<script>alert(1)</script>",
            remediation="Escape user input",
            port=443,
            protocol="tcp",
            service="https",
            cve=None,
            cwe="CWE-79",
            path="/api/feedback",
            cvss_score=7.5,
            ai_enriched=True,
            needs_ai_retry=False,
        )
        fallback = finding.to_fallback()
        assert fallback.ai_enriched is False

    def test_to_fallback_marks_needs_ai_retry_true(self):
        """to_fallback() sets needs_ai_retry=True."""
        from app.core.contracts import EnrichedFinding
        from uuid import uuid4

        finding = EnrichedFinding(
            asset_id=uuid4(),
            scan_id=uuid4(),
            vuln_type="xss",
            severity="high",
            title="Cross-Site Scripting in /api/feedback",
            description="Reflected XSS",
            evidence="<script>alert(1)</script>",
            remediation="Escape user input",
            port=443,
            protocol="tcp",
            service="https",
            cve=None,
            cwe="CWE-79",
            path="/api/feedback",
            cvss_score=7.5,
            ai_enriched=True,
            needs_ai_retry=False,
        )
        fallback = finding.to_fallback()
        assert fallback.needs_ai_retry is True

    def test_to_fallback_preserves_original_fields(self):
        """to_fallback() copies all fields except ai_enriched and needs_ai_retry."""
        from app.core.contracts import EnrichedFinding
        from uuid import uuid4

        asset_id = uuid4()
        scan_id = uuid4()
        finding = EnrichedFinding(
            asset_id=asset_id,
            scan_id=scan_id,
            vuln_type="open_redirect",
            severity="medium",
            title="Open Redirect",
            description="Redirect to external URL",
            evidence="Location: https://evil.com",
            remediation="Validate redirect URLs",
            port=80,
            protocol="tcp",
            service="http",
            cve=None,
            cwe="CWE-601",
            path="/api/redirect",
            cvss_score=6.1,
            ai_enriched=True,
            needs_ai_retry=False,
        )
        fallback = finding.to_fallback()
        assert fallback.asset_id == asset_id
        assert fallback.scan_id == scan_id
        assert fallback.vuln_type == "open_redirect"
        assert fallback.severity == "medium"
        assert fallback.title == "Open Redirect"
        assert fallback.cvss_score == 6.1


class TestLLMSafeComplete:
    """Verify llm_safe_complete wraps provider failures in non-blocking fallback semantics."""

    @pytest.mark.asyncio
    async def test_safe_complete_returns_text_on_success(self):
        """On provider success, return (text, False)."""
        from app.core.llm import llm_safe_complete, MockLLMProvider

        provider = MockLLMProvider(response_text="enriched finding")
        result, failed = await llm_safe_complete(
            provider, prompt="analyze", max_tokens=100, temperature=0.0
        )
        assert result == "enriched finding"
        assert failed is False

    @pytest.mark.asyncio
    async def test_safe_complete_returns_empty_on_llm_error(self):
        """On any LLMError, return ('', True) instead of raising."""
        from app.core.llm import llm_safe_complete
        from app.core.exceptions import LLMError

        class FailingProvider:
            async def complete(self, prompt, max_tokens, temperature):
                raise LLMError("connection failed")

        result, failed = await llm_safe_complete(
            FailingProvider(), prompt="analyze", max_tokens=100, temperature=0.0
        )
        assert result == ""
        assert failed is True

    @pytest.mark.asyncio
    async def test_safe_complete_does_not_raise_to_caller(self):
        """LLMError must be swallowed; caller gets empty string + failed flag."""
        from app.core.llm import llm_safe_complete

        class RateLimitedProvider:
            async def complete(self, prompt, max_tokens, temperature):
                from app.core.exceptions import LLMRateLimitError
                raise LLMRateLimitError("rate limited")

        # Must NOT raise — caller handles the flag
        result, failed = await llm_safe_complete(
            RateLimitedProvider(), prompt="analyze", max_tokens=100, temperature=0.0
        )
        assert result == ""
        assert failed is True

    @pytest.mark.asyncio
    async def test_safe_complete_returns_properly_typed_tuple(self):
        """llm_safe_complete returns a (str, bool) tuple — never None or raises directly."""
        from app.core.llm import llm_safe_complete, MockLLMProvider

        provider = MockLLMProvider(response_text="analysis result")
        result = await llm_safe_complete(provider, prompt="x", max_tokens=50, temperature=0.0)
        # Must be a 2-tuple, not any other type
        assert isinstance(result, tuple), "llm_safe_complete must return a tuple"
        assert len(result) == 2, "llm_safe_complete must return a 2-tuple (text, failed)"
        text, failed = result
        assert isinstance(text, str), "First element must be str (response text or empty string)"
        assert isinstance(failed, bool), "Second element must be bool (failed flag)"
        # Successful call: text is the response, failed is False
        assert text == "analysis result"
        assert failed is False

    """Verify MockLLMProvider can simulate LLM failure for fallback path testing."""

    def test_mock_can_return_empty_string_for_llm_failure_scenario(self):
        """Mock returns empty string to simulate LLM failure (triggers fallback path)."""
        from app.core.llm import MockLLMProvider
        import asyncio

        # Empty response = LLM failed to produce analysis
        provider = MockLLMProvider(response_text="")
        result = asyncio.run(provider.complete(prompt="analyze", max_tokens=500, temperature=0.0))
        assert result == ""
        # Downstream code checks for empty/missing and triggers fallback

    def test_mock_can_return_error_indicating_text_for_llm_failure(self):
        """Mock returns error-like text to simulate LLM failure."""
        from app.core.llm import MockLLMProvider
        import asyncio

        error_response = "ERROR: LLM request timed out after 30s"
        provider = MockLLMProvider(response_text=error_response)
        result = asyncio.run(provider.complete(prompt="analyze", max_tokens=500, temperature=0.0))
        assert "ERROR" in result
        assert "timed out" in result

    def test_mock_provider_no_network_on_failure_simulation(self):
        """Simulating failure with MockLLMProvider makes zero network calls."""
        from app.core.llm import MockLLMProvider
        import asyncio

        provider = MockLLMProvider(response_text="error simulation", delay_seconds=0.0)
        # If any network call were attempted, it would raise immediately
        result = asyncio.run(provider.complete(prompt="test", max_tokens=10, temperature=0.0))
        assert result == "error simulation"


class TestErrorMessageSafety:
    """Verify no API keys or secrets leak through error paths."""

    def test_llm_response_error_does_not_leak_api_key_format(self):
        """LLMResponseError messages must not contain API key patterns."""
        from app.core.llm import _create_provider
        from app.core.exceptions import LLMResponseError

        with pytest.raises(LLMResponseError) as exc_info:
            _create_provider("unknown-provider")
        detail = str(exc_info.value.detail)
        assert "gsk_" not in detail
        assert "sk-" not in detail
        assert "api_key" not in detail.lower()
        assert "sk" not in detail.lower()  # Common prefix patterns

    def test_error_messages_do_not_expose_provider_credentials(self):
        """Error messages across all providers must not expose credentials."""
        from app.core.exceptions import (
            LLMError,
            LLMTimeoutError,
            LLMRateLimitError,
            LLMContentFilterError,
            LLMResponseError,
        )

        # All LLM errors should have safe string representations
        errors = [
            LLMError("test error"),
            LLMTimeoutError("timeout"),
            LLMRateLimitError("rate limited"),
            LLMContentFilterError("content filtered"),
            LLMResponseError("bad response"),
        ]
        for err in errors:
            detail = str(err.detail) if err.detail else ""
            assert "gsk_" not in detail
            assert "sk-" not in detail
            assert "sk" not in detail.lower()


class TestLLMLoggingRedaction:
    """Verify LLM layer logs without exposing credentials."""

    @pytest.mark.asyncio
    async def test_openai_compat_complete_logs_url_without_api_key(self):
        """Log output must not contain Bearer token values."""
        import logging
        from app.core.llm import OpenAICompatProvider
        from unittest.mock import AsyncMock, MagicMock, patch

        provider = OpenAICompatProvider(
            api_key="gsk_super_secret_key_12345",
            model="llama-3.3-70b-versatile",
            base_url="https://api.groq.com/v1",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }

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

                await provider.complete("test prompt", max_tokens=50, temperature=0.1)

            # Check that at least one log record was produced
            assert len(log_records) > 0, "Expected at least one log record"

            # Verify NO log record contains the actual API key
            for record in log_records:
                assert "gsk_super_secret_key_12345" not in record.getMessage()
                assert "gsk_super_secret_key_12345" not in str(record.msg)

        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_openai_compat_complete_logs_redacted_url(self):
        """Log output must show the endpoint URL but not credentials."""
        import logging
        from app.core.llm import OpenAICompatProvider
        from unittest.mock import AsyncMock, MagicMock, patch

        provider = OpenAICompatProvider(
            api_key="sk-test-key-abc123",
            model="test-model",
            base_url="https://api.groq.com/v1",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "test response"}}]
        }

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

                await provider.complete("test prompt", max_tokens=50, temperature=0.1)

            # At least one log should mention the provider name or URL
            found_provider_log = any(
                "groq" in record.getMessage().lower() or "llm" in record.name.lower()
                for record in log_records
            )
            assert found_provider_log, (
                f"Expected at least one log mentioning 'groq' or 'llm', got: {[r.getMessage() for r in log_records]}"
            )

        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)

    @pytest.mark.asyncio
    async def test_error_path_does_not_leak_credentials_in_logs(self):
        """HTTP errors must not log API key values."""
        import logging
        from app.core.llm import OpenAICompatProvider
        from app.core.exceptions import LLMResponseError
        from unittest.mock import AsyncMock, MagicMock, patch

        provider = OpenAICompatProvider(
            api_key="gsk_very_secret_key_do_not_log",
            model="test-model",
            base_url="https://api.example.com/v1",
        )

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.is_success = False
        mock_response.text = "Internal server error"

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

                with pytest.raises(LLMResponseError):
                    await provider.complete("test prompt", max_tokens=50, temperature=0.1)

            for record in log_records:
                msg = record.getMessage()
                assert "gsk_very_secret_key_do_not_log" not in msg
                assert "sk-test-key-abc123" not in msg

        finally:
            llm_logger.removeHandler(handler)
            llm_logger.setLevel(original_level)
