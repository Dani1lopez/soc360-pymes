"""Tests for app/core/metrics_auth.py + the metrics token config fields (PR4 #260).

Phase 2 covers the primitive auth module directly; Phase 4 covers end-to-end.
Tests follow the documented ``monkeypatch.setattr(settings, "METRICS_TOKEN", ...)``
+ ``_current_bytes.cache_clear()`` contract from design rev 16.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.core import metrics_auth
from app.core.config import settings


def _make_settings(**overrides):
    """Construct a ``Settings`` instance; ``_env_file=None`` isolates from operator ``.env``."""
    from app.core.config import Settings

    base = dict(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://test:test@localhost/test",
        DATABASE_URL_MIGRATION="postgresql+asyncpg://test:test@localhost/test",
        POSTGRES_USER="test",
        POSTGRES_PASSWORD="test",
        POSTGRES_DB="test",
        SECRET_KEY="".join(chr(ord("a") + (i % 26)) for i in range(128)),
        LLM_PROVIDER="ollama",
        ENVIRONMENT="development",
    )
    base.update(overrides)
    return Settings(**base)


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

    def test_previous_token_revoked_after_drop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spec #3: After ``METRICS_TOKEN_PREVIOUS`` is removed, the old token MUST NOT authenticate.

        During rotation overlap, both ``current`` and ``previous`` authenticate. After
        ``METRICS_TOKEN_PREVIOUS`` is dropped (e.g., set to ``None``), the old token must
        no longer be accepted — proves the rotation retirement semantics.
        """
        # During overlap: both authenticate.
        _install_tokens(monkeypatch, current="new-abc", previous="old-xyz")
        assert metrics_auth.verify_metrics_token("new-abc") is True
        assert metrics_auth.verify_metrics_token("old-xyz") is True

        # After dropoff: only current authenticates.
        _install_tokens(monkeypatch, current="new-abc", previous=None)
        assert metrics_auth.verify_metrics_token("new-abc") is True
        assert metrics_auth.verify_metrics_token("old-xyz") is False


class TestProductionStartupValidator:
    """Spec #1: Production startup MUST fail fast when ``METRICS_TOKEN`` is empty.

    Pins the ``metrics_token_required_in_production`` validator in
    ``app/core/config.py`` so a regression would abort the build.
    """

    def test_prod_without_metrics_token_aborts_startup(self) -> None:
        """Spec #1: ``ENVIRONMENT=production`` + empty ``METRICS_TOKEN`` MUST raise."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings(ENVIRONMENT="production", METRICS_TOKEN=None)
        assert "METRICS_TOKEN" in str(exc_info.value), (
            f"ValidationError should mention METRICS_TOKEN, got: {exc_info.value!r}"
        )

    def test_prod_with_only_previous_token_aborts_startup(self) -> None:
        """Spec #1: ``METRICS_TOKEN_PREVIOUS`` alone MUST NOT satisfy production."""
        with pytest.raises(ValidationError) as exc_info:
            _make_settings(
                ENVIRONMENT="production",
                METRICS_TOKEN=None,
                METRICS_TOKEN_PREVIOUS=SecretStr("previous-only"),
            )
        assert "METRICS_TOKEN" in str(exc_info.value), (
            f"ValidationError should mention METRICS_TOKEN, got: {exc_info.value!r}"
        )

    def test_prod_with_current_token_succeeds(self) -> None:
        """Spec #1 (positive): production with a valid current token MUST NOT raise."""
        s = _make_settings(
            ENVIRONMENT="production",
            METRICS_TOKEN=SecretStr("a-real-prod-token"),
        )
        assert s.ENVIRONMENT == "production"
        assert s.METRICS_TOKEN is not None

    def test_nonprod_without_token_succeeds(self) -> None:
        """Spec #1 (non-prod): empty tokens in dev MUST NOT abort startup."""
        s = _make_settings(ENVIRONMENT="development", METRICS_TOKEN=None)
        assert s.ENVIRONMENT == "development"
        assert s.METRICS_TOKEN is None


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
