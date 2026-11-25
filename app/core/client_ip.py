"""Client IP resolution for requests arriving through a trusted proxy (S8/H4).

The API is published behind the bundled nginx (``frontend/nginx.conf``), which
appends the peer address to ``X-Forwarded-For``. A request only carries a
usable ``X-Forwarded-For`` when the *socket peer* is one of the configured
``TRUSTED_PROXIES``; anything else — a client talking to the API directly, or a
header injected by an untrusted peer — is ignored and the socket peer is used.

Walking the forwarded chain from right to left and returning the first
untrusted hop defeats header spoofing: nginx appends the real peer to whatever
the client sent, so a forged leftmost entry can never become the rate-limit
identity.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Sequence
from functools import lru_cache

from app.core.config import settings

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=16)
def _parse_networks(entries: tuple[str, ...]) -> tuple[IPNetwork, ...]:
    """Parse configured CIDRs; an invalid entry never grants trust."""
    networks: list[IPNetwork] = []
    for entry in entries:
        text = entry.strip()
        if not text:
            continue
        try:
            networks.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def trusted_networks() -> tuple[IPNetwork, ...]:
    """Return the configured trusted-proxy networks (settings default)."""
    return _parse_networks(tuple(settings.TRUSTED_PROXIES))


def parse_ip(value: str | None) -> IPAddress | None:
    """Parse an IP literal, tolerating the IPv6 bracket form."""
    if not value:
        return None
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        return None


def _in_networks(address: IPAddress, networks: Sequence[IPNetwork]) -> bool:
    return any(
        network.version == address.version and address in network
        for network in networks
    )


def is_trusted_proxy(host: str | None) -> bool:
    """True when ``host`` is a configured trusted proxy address."""
    address = parse_ip(host)
    if address is None:
        return False
    return _in_networks(address, trusted_networks())


def resolve_client_ip(
    peer_host: str | None,
    forwarded_for: str | None,
    trusted: Sequence[str] | None = None,
) -> str:
    """Return the client IP for rate limiting and audit events.

    ``forwarded_for`` is only consulted when the socket peer is trusted. The
    rightmost non-trusted hop of the chain wins; if the whole chain is trusted
    (or unparsable) the socket peer is kept.
    """
    peer_text = (peer_host or "").strip()
    peer = parse_ip(peer_text)
    if peer is None:
        return peer_text or "unknown"

    networks = (
        trusted_networks() if trusted is None else _parse_networks(tuple(trusted))
    )
    if not networks or not _in_networks(peer, networks):
        return str(peer)

    if not forwarded_for:
        return str(peer)

    hops = [hop for hop in (parse_ip(part) for part in forwarded_for.split(",")) if hop]
    for hop in reversed(hops):
        if not _in_networks(hop, networks):
            return str(hop)

    return str(peer)
