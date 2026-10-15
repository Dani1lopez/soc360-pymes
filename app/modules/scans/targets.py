"""Scan-time target validation: reject unsafe, non-private or oversized targets.

Asset syntax is revalidated immediately before launch (F2 slice 5, decisions
1 and 8). DNS is resolved here exactly once and only the validated IPs
reach Nmap, preventing a second lookup from bypassing the authorization gate.
This module performs no database access or process execution.

H2 decision D2=A: scans only reach RFC1918/ULA private networks, so a deployment
can never be pointed at a third party's public address. The network policy is
deliberately independent of ``SCAN_DEMO_MODE``, which only selects the fast Nmap
profile: enabling the local demo switch must not widen what is scannable.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.modules.assets.service import _validate_asset_value

Resolver = Callable[[str], Awaitable[list[str]]]

# A hanging DNS lookup would leave a claimed scan running indefinitely.
RESOLUTION_TIMEOUT_SECONDS = 10.0


class TargetRejectedError(ValueError):
    """A target gate failure with a stable, persistable failure reason."""

    reason: str

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class ScanTarget:
    """Original asset value and the exact arguments Nmap may scan."""

    asset_type: str
    original: str
    addresses: tuple[str, ...]


async def _resolve_host(host: str) -> list[str]:
    results = await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(address[0]) for _, _, _, _, address in results))


# Only these ranges are scannable: RFC1918 for IPv4 and unique-local for IPv6.
_SCAN_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
# IPv6 forms that embed an IPv4 address and could smuggle a forbidden one past the filter.
_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("2002::/16", "64:ff9b::/96", "2001::/32")
)


def _allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or any(address in network for network in _TRANSITION_NETWORKS)
    ):
        return False
    return any(address in network for network in _SCAN_PRIVATE_NETWORKS)


def _allowed_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise TargetRejectedError("target_invalid") from exc
    if not _allowed_address(address):
        raise TargetRejectedError("target_not_allowed")
    return str(address)


async def resolve_scan_target(
    asset_type: str,
    value: str,
    *,
    resolver: Resolver | None = None,
    resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
) -> ScanTarget:
    """Canonicalize syntax and apply the private-network target policy.

    Subnets contain at most 256 addresses (/24 IPv4 or /120 IPv6) and must be a
    subset of a private range. Unsupported asset types are rejected without
    resolution; URL credentials never appear in errors. ``original`` retains the
    supplied asset value for the caller.
    """
    if asset_type not in {"ip", "subnet", "hostname", "domain", "web_app"}:
        raise TargetRejectedError("target_unsupported_type")
    try:
        canonical = _validate_asset_value(asset_type, value)
    except ValueError as exc:
        raise TargetRejectedError("target_invalid") from exc
    if canonical.startswith("-"):
        raise TargetRejectedError("target_invalid")

    addresses: tuple[str, ...]
    if asset_type == "ip":
        addresses = (_allowed_ip(canonical),)
    elif asset_type == "subnet":
        network = ipaddress.ip_network(canonical, strict=False)
        if network.num_addresses > 256:
            raise TargetRejectedError("target_too_large")
        # A subnet must sit entirely inside one private range: checking both
        # boundaries would let a range that spans two blocks through.
        if not any(
            network.version == private.version and network.subnet_of(private)
            for private in _SCAN_PRIVATE_NETWORKS
        ):
            raise TargetRejectedError("target_not_allowed")
        addresses = (str(network),)
    else:
        host = canonical
        if asset_type == "web_app":
            host = urlsplit(canonical).hostname or ""
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                return ScanTarget(asset_type, value, (_allowed_ip(host),))
        try:
            async with asyncio.timeout(resolution_timeout):
                resolved = await (resolver or _resolve_host)(host)
        except TimeoutError as exc:
            raise TargetRejectedError("target_resolution_timeout") from exc
        except socket.gaierror as exc:
            raise TargetRejectedError("target_unresolvable") from exc
        if not resolved:
            raise TargetRejectedError("target_unresolvable")
        addresses = tuple(_allowed_ip(address) for address in resolved)
    return ScanTarget(asset_type, value, addresses)
