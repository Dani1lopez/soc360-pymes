"""Tests for app/core/pii.py — PII sanitization helpers."""
from __future__ import annotations

import pytest

from app.core.pii import hash_email, mask_ip, sanitize_user_agent


class TestHashEmail:
    """Validate hash_email behaviour."""

    def test_hash_email_returns_32_char_hex(self):
        """hash_email MUST return a 32-character hexadecimal string."""
        result = hash_email("user@example.com")
        assert result is not None
        assert len(result) == 32
        assert int(result, 16) >= 0  # valid hex

    def test_hash_email_with_none_returns_none(self):
        """hash_email MUST return None when input is None."""
        assert hash_email(None) is None

    def test_hash_email_with_empty_string_returns_none(self):
        """hash_email MUST return None when input is empty string."""
        assert hash_email("") is None


class TestMaskIp:
    """Validate mask_ip behaviour."""

    def test_mask_ip_ipv4_returns_24_prefix(self):
        """mask_ip MUST return /24 prefix for a valid IPv4 address."""
        result = mask_ip("192.168.1.100")
        assert result == "192.168.1.0/24"

    def test_mask_ip_ipv6_returns_64_prefix(self):
        """mask_ip MUST return /64 prefix for a valid IPv6 address."""
        result = mask_ip("2001:db8::1")
        assert result == "2001:db8::/64"

    def test_mask_ip_with_none_returns_none(self):
        """mask_ip MUST return None when input is None."""
        assert mask_ip(None) is None

    def test_mask_ip_with_empty_string_returns_none(self):
        """mask_ip MUST return None when input is empty string."""
        assert mask_ip("") is None

    def test_mask_ip_non_ipv4_returns_original(self):
        """mask_ip MUST return original string for non-IPv4 input."""
        assert mask_ip("not-an-ip") == "not-an-ip"


class TestSanitizeUserAgent:
    """Validate sanitize_user_agent behaviour (REQ-140-R08)."""

    def test_none_returns_none(self):
        """sanitize_user_agent MUST return None when input is None."""
        assert sanitize_user_agent(None) is None

    def test_empty_string_returns_none(self):
        """sanitize_user_agent MUST return None for empty string."""
        assert sanitize_user_agent("") is None

    def test_whitespace_only_returns_none(self):
        """sanitize_user_agent MUST return None for whitespace-only input."""
        assert sanitize_user_agent("   \t  \n  ") is None

    def test_control_chars_are_replaced(self):
        """Control characters MUST be replaced with space."""
        result = sanitize_user_agent("Mozilla\x00Foo\x1fBar\x7f")
        assert result is not None
        assert "\x00" not in result
        assert "\x1f" not in result
        assert "\x7f" not in result
        # Replaced with spaces, then collapsed
        assert result == "Mozilla Foo Bar"

    def test_whitespace_is_collapsed(self):
        """Runs of whitespace MUST be collapsed to single space."""
        result = sanitize_user_agent("Mozilla/5.0   (Linux;   Android 13)")
        assert result == "Mozilla/5.0 (Linux; Android 13)"

    def test_long_ua_is_capped_at_256(self):
        """Output MUST be capped at 256 characters."""
        long_ua = "Mozilla/5.0 " + "x" * 500
        result = sanitize_user_agent(long_ua)
        assert result is not None
        assert len(result) == 256

    def test_normal_ua_passes_through(self):
        """Normal User-Agent MUST remain unchanged (except whitespace normalization)."""
        ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        result = sanitize_user_agent(ua)
        assert result == ua

    def test_leading_trailing_whitespace_stripped(self):
        """Leading and trailing whitespace MUST be stripped."""
        result = sanitize_user_agent("  Chrome/120  ")
        assert result == "Chrome/120"
