"""Scan-time target validation: reject unsafe or oversized targets.

Asset syntax is revalidated immediately before launch (F2 slice 5, decisions
1 and 8). DNS is resolved here exactly once and only the validated IPs
reach Nmap, preventing a second lookup from bypassing the authorization gate.
This module performs no database access or process execution.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.config import settings
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


# Demo mode adds only these private ranges on top of global addresses; documentation,
# benchmarking and similar "private" blocks are deliberately not demo targets.
_DEMO_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)
# IPv6 forms that embed an IPv4 address and could smuggle a forbidden one past the filter.
_DEMO_TRANSITION_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("2002::/16", "64:ff9b::/96", "2001::/32")
)


def _allowed_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not settings.SCAN_DEMO_MODE:
        return address.is_global
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or any(address in network for network in _DEMO_TRANSITION_NETWORKS)
    ):
        return False
    return address.is_global or any(
        address in network for network in _DEMO_PRIVATE_NETWORKS
    )


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise TargetRejectedError("target_invalid") from exc
    if not _allowed_address(address):
        raise TargetRejectedError("target_not_global")
    return str(address)


async def resolve_scan_target(
    asset_type: str,
    value: str,
    *,
    resolver: Resolver | None = None,
    resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
) -> ScanTarget:
    """Canonicalize syntax and apply the global-only or local demo target policy.

    Subnets contain at most 256 addresses (/24 IPv4 or /120 IPv6). Unsupported
    asset types are rejected without resolution; URL credentials never appear
    in errors. ``original`` retains the supplied asset value for the caller.
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
        addresses = (_public_ip(canonical),)
    elif asset_type == "subnet":
        network = ipaddress.ip_network(canonical, strict=False)
        if network.num_addresses > 256:
            raise TargetRejectedError("target_too_large")
        allowed = network.is_global
        if settings.SCAN_DEMO_MODE:
            # Check both boundaries so a subnet cannot include forbidden addresses.
            allowed = _allowed_address(network.network_address) and _allowed_address(
                network.broadcast_address
            )
        if not allowed:
            raise TargetRejectedError("target_not_global")
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
                return ScanTarget(asset_type, value, (_public_ip(host),))
        try:
            async with asyncio.timeout(resolution_timeout):
                resolved = await (resolver or _resolve_host)(host)
        except TimeoutError as exc:
            raise TargetRejectedError("target_resolution_timeout") from exc
        except socket.gaierror as exc:
            raise TargetRejectedError("target_unresolvable") from exc
        if not resolved:
            raise TargetRejectedError("target_unresolvable")
        addresses = tuple(_public_ip(address) for address in resolved)
    return ScanTarget(asset_type, value, addresses)
