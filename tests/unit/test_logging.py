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
        "cookie",
        "set-cookie",
        "x-api-key",
        "Refresh_Token",
        "Set-Cookie",
        "X-API-Key",
        "PASSWORD_HASH",
    ],
)
def test_filter_sensitive_data_redacts_secret_keys(key: str) -> None:
    event = {"event": "auth_action", key: "super-secret-value", "token_type": "bearer"}
    result = _filter_sensitive_data(None, "info", event)

    assert result[key] == "***REDACTED***"
    assert result["token_type"] == "bearer"
    assert result["event"] == "auth_action"


def test_filter_sensitive_data_masks_scoped_ipv6_without_leaking_zone() -> None:
    result = _filter_sensitive_data(None, "info", {"client_ip": "fe80::1%eth0"})

    assert result == {"client_ip": "fe80:0000:***"}
    assert "eth0" not in result["client_ip"]


@pytest.mark.parametrize("value", ["192.0.2.1%eth0", "fe80::1%"])
def test_filter_sensitive_data_redacts_malformed_scoped_ips(value: str) -> None:
    result = _filter_sensitive_data(None, "info", {"client_ip": value})

    assert result == {"client_ip": "***"}


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


def test_filter_sensitive_data_redacts_dicts_inside_lists_and_tuples_without_mutation() -> (
    None
):
    user = {"password": "fixture"}
    nested = [{"token": "fixture"}]
    users = [user, nested]
    tuple_users = ({"api_key": "fixture"},)
    event = {"users": users, "tuple_users": tuple_users}

    result = _filter_sensitive_data(None, "info", event)

    assert result["users"] == [
        {"password": "***REDACTED***"},
        [{"token": "***REDACTED***"}],
    ]
    assert result["tuple_users"] == ({"api_key": "***REDACTED***"},)
    assert isinstance(result["tuple_users"], tuple)
    assert users == [user, nested] == [{"password": "fixture"}, [{"token": "fixture"}]]
    assert tuple_users == ({"api_key": "fixture"},)


def test_redacts_through_depth_five_without_mutating_input() -> None:
    event = {"token": "fixture"}
    for _ in range(5):
        event = {"nested": event}
    result = _filter_sensitive_data(None, "info", event)
    original = event
    for _ in range(5):
        original, result = original["nested"], result["nested"]
    assert result == {"token": "***REDACTED***"}
    assert original == {"token": "fixture"}


def test_filter_sensitive_data_does_not_mutate_caller_dicts_or_crash_on_non_str_keys() -> (
    None
):
    caller_payload = {"refresh_token": "rt-secret", 1: "numeric-key", "ip": "10.0.0.1"}
    event = {"event": "test", "payload": caller_payload}

    result = _filter_sensitive_data(None, "info", event)

    assert result["payload"] == {
        "refresh_token": "***REDACTED***",
        1: "numeric-key",
        "ip": "10.0.***.***",
    }
    assert caller_payload == {
        "refresh_token": "rt-secret",
        1: "numeric-key",
        "ip": "10.0.0.1",
    }
