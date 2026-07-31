"""Cancel-safe Redis distributed-lock primitives."""

from __future__ import annotations

import hashlib
import hmac
import re

from app.core.config import settings


_LOCK_RESOURCE_SUPERADMIN_SESSION = "__SUPERADMIN_SESSION__"
_LOCK_RESOURCE_TENANT_DEACTIVATION = "__TENANT_DEACTIVATION__"
LOCK_MIN_TTL_SECONDS: int = 1

_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_-]+")


def _safe_component(value: str) -> str:
    if value and _SAFE_COMPONENT.fullmatch(value):
        return value
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _lock_key_secret() -> bytes:
    configured_secret = getattr(settings, "LOCK_KEY_SECRET", None)
    if configured_secret is None:
        raise ValueError("LOCK_KEY_SECRET is required for distributed locks")

    secret = (
        configured_secret.get_secret_value()
        if hasattr(configured_secret, "get_secret_value")
        else str(configured_secret)
    )
    if not secret:
        raise ValueError("LOCK_KEY_SECRET is required for distributed locks")
    return secret.encode("utf-8")


def _flow_short(flow_id: str) -> str:
    return _safe_component(flow_id.split("_", 1)[0])


def build_lock_key(flow_id: str, tenant_id: str, asset_id: str) -> str:
    """Build the HMAC-namespaced key for a tenant/resource lock."""
    tenant = str(tenant_id)
    asset = str(asset_id)
    tenant_namespace = (
        hmac.new(_lock_key_secret(), tenant.encode("utf-8"), hashlib.sha256)
        .digest()[:8]
        .hex()
    )
    return ":".join(
        (
            "lock",
            _flow_short(str(flow_id)),
            tenant_namespace,
            _safe_component(tenant),
            _safe_component(asset),
        )
    )
