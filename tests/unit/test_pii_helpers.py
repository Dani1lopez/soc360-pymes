"""Tests for app/core/pii.py — PII sanitization helpers."""
from __future__ import annotations

import pytest

from app.core.pii import hash_email, mask_ip


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
