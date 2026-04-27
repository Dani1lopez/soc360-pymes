from __future__ import annotations

import hashlib


def hash_email(email: str | None) -> str | None:
    """Return SHA-256 hash of email truncated to 16 hex characters, or None."""
    if not email:
        return None
    return hashlib.sha256(email.encode()).hexdigest()[:16]


def mask_ip(ip_address: str | None) -> str | None:
    """Return IPv4 /24 prefix mask (e.g. 192.168.1.0/24), or None."""
    if not ip_address:
        return None
    parts = ip_address.split(".")
    if len(parts) == 4:
        return ".".join(parts[:3]) + ".0/24"
    return ip_address
