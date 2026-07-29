"""Tests for app/core/metrics_auth.py + the metrics token config fields (PR4 #260).

Phase 2 covers the primitive auth module directly; Phase 4 covers end-to-end.
Tests follow the documented ``monkeypatch.setattr(settings, "METRICS_TOKEN", ...)``
+ ``_current_bytes.cache_clear()`` contract from design rev 15.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr
from starlette.datastructures import Headers

from app.core import metrics_auth
from app.core.config import settings


def _install_tokens(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: str | None = None,
    previous: str | None = None,
) -> None:
    """Install tokens on the module-level ``settings`` singleton and clear caches."""
    monkeypatch.setattr(
        settings,
        "METRICS_TOKEN",
        SecretStr(current) if current is not None else None,
    )
    monkeypatch.setattr(
        settings,
        "METRICS_TOKEN_PREVIOUS",
        SecretStr(previous) if previous is not None else None,
    )
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()


def _mock_request(raw_pairs: list[tuple[bytes, bytes]]) -> object:
    """Minimal request-like object exposing ``.headers.getlist``."""
    return type("MockReq", (), {"headers": Headers(raw=raw_pairs)})()


@pytest.fixture(autouse=True)
def _clear_caches():
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()
    yield
    metrics_auth._current_bytes.cache_clear()
    metrics_auth._previous_bytes.cache_clear()


class TestModuleExports:
    def test_metrics_token_header_constant(self) -> None:
        assert metrics_auth.METRICS_TOKEN_HEADER == "x-metrics-token"

    def test_metrics_token_max_bytes_constant(self) -> None:
        assert metrics_auth.METRICS_TOKEN_MAX_BYTES == 256


class TestExtractHeaderMissing:
    def test_no_header_returns_empty(self) -> None:
        assert metrics_auth._extract_header(_mock_request([])) == ""


class TestExtractHeaderDuplicates:
    def test_single_header_passes_extraction(self) -> None:
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b"abc")])) == "abc"

    @pytest.mark.parametrize(
        "raw_pairs",
        [
            [(b"x-metrics-token", b"abc"), (b"x-metrics-token", b"abc")],
            [(b"x-metrics-token", b"abc"), (b"x-metrics-token", b"def")],
        ],
    )
    def test_duplicate_header_returns_empty(self, raw_pairs) -> None:
        """Two copies of x-metrics-token MUST be rejected (RFC 7230 §3.2.2)."""
        assert metrics_auth._extract_header(_mock_request(raw_pairs)) == ""


class TestExtractHeaderByteCap:
    def test_at_limit_passes_extraction(self) -> None:
        payload = b"a" * 256
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", payload)])) == "a" * 256

    def test_over_limit_returns_empty(self) -> None:
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b"a" * 257)])) == ""

    def test_one_megabyte_whitespace_payload_rejected_via_byte_cap(self) -> None:
        """1 MB whitespace payload MUST be rejected at the byte cap before ``isspace()`` work."""
        assert (
            metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b" " * (1 << 20))]))
            == ""
        )


class TestExtractHeaderWhitespace:
    @pytest.mark.parametrize(
        "value",
        [
            " abc", "abc ", "a b", "\tabc", "abc\n", "a\tb", "a\rb",
        ],
    )
    def test_whitespace_rejected_not_stripped(self, value: str) -> None:
        """Whitespace MUST be rejected (NOT ``.strip()``-normalized)."""
        assert (
            metrics_auth._extract_header(_mock_request([(b"x-metrics-token", value.encode("utf-8"))]))
            == ""
        )


class TestExtractHeaderNonAscii:
    def test_ascii_passes(self) -> None:
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b"abc-def_123")])) == "abc-def_123"

    def test_raw_ff_byte_rejected(self) -> None:
        """0xff is not a valid UTF-8 start byte; Starlette latin-1-decodes it; ``isascii()`` rejects."""
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b"abc\xff")])) == ""

    def test_overlong_utf8_rejected(self) -> None:
        """Overlong UTF-8 (0xc0 0x80) rejected under latin-1 + isascii."""
        assert metrics_auth._extract_header(_mock_request([(b"x-metrics-token", b"abc\xc0\x80")])) == ""


class TestVerifyMetricsToken:
    """``verify_metrics_token`` MUST use a non-short-circuiting bitwise combinator."""

    def test_empty_presented_never_authenticates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-token")
        assert metrics_auth.verify_metrics_token("") is False

    def test_current_token_matches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-token")
        assert metrics_auth.verify_metrics_token("current-token") is True

    def test_wrong_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-token")
        assert metrics_auth.verify_metrics_token("wrong-token") is False

    def test_case_mismatched_token_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-token")
        assert metrics_auth.verify_metrics_token("Current-Token") is False

    def test_previous_token_matches_during_overlap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="new-abc", previous="old-xyz")
        assert metrics_auth.verify_metrics_token("new-abc") is True
        assert metrics_auth.verify_metrics_token("old-xyz") is True

    def test_unrelated_token_rejected_when_both_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="new-abc", previous="old-xyz")
        assert metrics_auth.verify_metrics_token("never-set") is False

    def test_only_current_set_rejects_previous_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-only")
        assert metrics_auth.verify_metrics_token("current-only") is True
        assert metrics_auth.verify_metrics_token("some-old-value") is False

    def test_no_tokens_always_rejects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch)
        assert metrics_auth.verify_metrics_token("") is False
        assert metrics_auth.verify_metrics_token("anything") is False


class TestUnauthorizedResponseByteIdentity:
    def test_status_is_401(self) -> None:
        assert metrics_auth._unauthorized_response().status_code == 401

    def test_body_contains_only_unauthorized_detail(self) -> None:
        from json import loads
        assert loads(metrics_auth._unauthorized_response().body) == {"detail": "unauthorized"}

    def test_two_calls_are_byte_identical(self) -> None:
        first = metrics_auth._unauthorized_response()
        second = metrics_auth._unauthorized_response()
        assert first.status_code == second.status_code
        assert first.body == second.body


class TestCachedBytes:
    def test_current_encodes_to_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="current-abc")
        assert metrics_auth._current_bytes() == b"current-abc"

    def test_previous_encodes_to_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="cur", previous="prev")
        assert metrics_auth._previous_bytes() == b"prev"

    def test_none_settings_yield_empty_bytes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch)
        assert metrics_auth._current_bytes() == b""
        assert metrics_auth._previous_bytes() == b""

    def test_cache_clear_invalidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_tokens(monkeypatch, current="first")
        assert metrics_auth._current_bytes() == b"first"
        metrics_auth._current_bytes.cache_clear()
        _install_tokens(monkeypatch, current="second")
        assert metrics_auth._current_bytes() == b"second"
