"""Unit tests for the Redis distributed-lock primitive."""

from __future__ import annotations

import hashlib
import hmac
import re
from types import SimpleNamespace

import pytest
from pydantic import SecretStr


def _settings(secret: str) -> SimpleNamespace:
    return SimpleNamespace(LOCK_KEY_SECRET=SecretStr(secret))


def test_build_lock_key_returns_expected_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import dist_lock

    secret = "a sufficiently long lock key secret"
    monkeypatch.setattr(dist_lock, "settings", _settings(secret))

    key = dist_lock.build_lock_key("scan", "t1", "a1")
    expected_hmac = hmac.new(secret.encode(), b"t1", hashlib.sha256).digest()[:8].hex()

    assert key == f"lock:scan:{expected_hmac}:t1:a1"
    assert re.fullmatch(r"[0-9a-f]{16}", key.split(":")[2])


def test_build_lock_key_tenant_segment_changes_with_secret_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import dist_lock

    monkeypatch.setattr(dist_lock, "settings", _settings("first secret"))
    first_key = dist_lock.build_lock_key("scan", "tenant-1", "asset-1")

    monkeypatch.setattr(dist_lock, "settings", _settings("rotated secret"))
    rotated_key = dist_lock.build_lock_key("scan", "tenant-1", "asset-1")

    assert first_key.split(":")[2] != rotated_key.split(":")[2]
    assert first_key.rsplit(":", 2)[-2:] == rotated_key.rsplit(":", 2)[-2:]


@pytest.mark.parametrize(
    "resource",
    ["__SUPERADMIN_SESSION__", "__TENANT_DEACTIVATION__"],
)
def test_build_lock_key_handles_reserved_sentinels(
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
) -> None:
    from app.core import dist_lock

    monkeypatch.setattr(dist_lock, "settings", _settings("sentinel secret"))

    key = dist_lock.build_lock_key("auth", "tenant-1", resource)

    assert key.rsplit(":", 1)[-1] == resource
    assert ":" not in resource
    assert not any(character.isspace() for character in resource)


def test_build_lock_key_safe_component_encodes_invalid_chars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import dist_lock

    monkeypatch.setattr(dist_lock, "settings", _settings("component secret"))

    key = dist_lock.build_lock_key("scan", "tenant:42", "asset-1")
    tenant_segment = key.split(":")[3]

    assert tenant_segment == hashlib.sha256(b"tenant:42").hexdigest()
    assert ":" not in tenant_segment


def test_lock_minimum_ttl_is_a_non_tunable_one_second_policy() -> None:
    from app.core.dist_lock import LOCK_MIN_TTL_SECONDS

    assert LOCK_MIN_TTL_SECONDS == 1
