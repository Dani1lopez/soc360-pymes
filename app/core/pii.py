from __future__ import annotations

import hashlib
import ipaddress


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
