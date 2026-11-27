"""Unit tests for log redaction and PII masking (Phase 1 S12 L2)."""

from __future__ import annotations

import pytest

from app.core.logging import _filter_sensitive_data


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "current_password",
        "new_password",
        "password_hash",
        "token",
        "refresh_token",
        "access_token",
        "secret",
        "api_key",
        "authorization",
        "Refresh_Token",
        "PASSWORD_HASH",
    ],
)
def test_filter_sensitive_data_redacts_secret_keys(key: str) -> None:
    event = {"event": "auth_action", key: "super-secret-value", "token_type": "bearer"}
    result = _filter_sensitive_data(None, "info", event)

    assert result[key] == "***REDACTED***"
    assert result["token_type"] == "bearer"
    assert result["event"] == "auth_action"


def test_filter_sensitive_data_masks_ips_and_emails() -> None:
    event = {
        "event": "login_attempt",
        "ip": "192.168.1.42",
        "client_ip": "2001:db8::1",
        "request_ip": "unknown",
        "email": "alice@example.com",
        "user_email": "a@b.co",
    }
    result = _filter_sensitive_data(None, "info", event)

    assert result["ip"] == "192.168.***.***"
    assert result["client_ip"] == "2001:0db8:***"
    assert result["request_ip"] == "***"
    assert result["email"] == "a***@example.com"
    assert result["user_email"] == "a***@b.co"


def test_filter_sensitive_data_handles_edge_cases_and_nested_dicts() -> None:
    event = {
        "event": "edge",
        "ip": None,
        "client_ip": "",
        "email": "not-an-email",
        "user_email": "@example.com",
        "payload": {
            "refresh_token": "rt-123",
            "new_password": "pw-456",
            "ip": "10.20.30.40",
            "email": "bob@corp.test",
            "max_tokens": 512,
        },
    }
    result = _filter_sensitive_data(None, "info", event)

    assert result["ip"] is None
    assert result["client_ip"] == ""
    assert result["email"] == "***"
    assert result["user_email"] == "***@example.com"
    assert result["payload"] == {
        "refresh_token": "***REDACTED***",
        "new_password": "***REDACTED***",
        "ip": "10.20.***.***",
        "email": "b***@corp.test",
        "max_tokens": 512,
    }
