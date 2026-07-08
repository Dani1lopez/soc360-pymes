from __future__ import annotations

import hashlib
import ipaddress
import re


def sanitize_user_agent(user_agent: str | None) -> str | None:
    """Sanitize a User-Agent string for safe event publication.

    * ``None``, empty, or whitespace-only → ``None``
    * Non-printable control characters are replaced with a space
    * Runs of whitespace are collapsed to a single space
    * Leading/trailing whitespace is stripped
    * Result is capped at 256 characters
    * If the result is empty after sanitization → ``None``
    """
    if not user_agent:
        return None

    # Replace control characters (0x00-0x1F except \t \n \r, and 0x7F) with space
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", user_agent)

    # Collapse whitespace runs
    cleaned = re.sub(r"\s+", " ", cleaned)

    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    # Cap at 256 characters
    return cleaned[:256]


def hash_email(email: str | None) -> str | None:
    """Return SHA-256 hash of email truncated to 32 hex characters, or None."""
    if not email:
        return None
    return hashlib.sha256(email.encode()).hexdigest()[:32]


def mask_ip(ip_address: str | None) -> str | None:
    """Return IPv4 /24 or IPv6 /64 prefix mask, or None."""
    if not ip_address:
        return None
    try:
        addr = ipaddress.ip_address(ip_address)
        if isinstance(addr, ipaddress.IPv4Address):
            return str(ipaddress.ip_network(f"{addr}/24", strict=False))
        if isinstance(addr, ipaddress.IPv6Address):
            return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    except ValueError:
        pass
    return ip_address
