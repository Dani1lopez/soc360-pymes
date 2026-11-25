"""Outbound address policy for requests the service makes on a tenant's behalf.

``app.modules.scans.targets`` applies the *opposite* policy to scans: only
RFC1918/ULA targets are scannable. This module governs the requests the service
itself makes, such as the ownership HTTP file challenge (H2/S2), and those must
never reach loopback, link-local (including the ``169.254.169.254`` cloud
metadata endpoint), unspecified, multicast, reserved or private addresses, nor a
hostname that resolves to one.

Resolution happens here exactly once and returns the single address the caller
must connect to, so a second lookup between the check and the fetch cannot
redirect the request (DNS rebinding).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable

Resolver = Callable[[str], Awaitable[list[str]]]

# A hanging lookup would leave a request open indefinitely.
RESOLUTION_TIMEOUT_SECONDS = 10.0

Address = ipaddress.IPv4Address | ipaddress.IPv6Address

# Carrier-grade NAT: not globally routable to the internet, but ``is_private``
# is not guaranteed to cover it on every supported Python version.
_SHARED_ADDRESS_SPACE = ipaddress.ip_network("100.64.0.0/10")
# IPv6 prefix that embeds an IPv4 address which must be checked on its own.
_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")


class AddressNotAllowedError(ValueError):
    """The service must never contact this address."""


class AddressResolutionError(OSError):
    """The host did not resolve to any address."""


def is_ip_literal(value: str) -> bool:
    """Whether the value is an address, not a name to resolve."""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _embedded_ipv4(address: Address) -> ipaddress.IPv4Address | None:
    """The IPv4 address smuggled inside an IPv6 form, if any."""
    if not isinstance(address, ipaddress.IPv6Address):
        return None
    if address.ipv4_mapped is not None:
        return address.ipv4_mapped
    if address.sixtofour is not None:
        return address.sixtofour
    if address.teredo is not None:
        return address.teredo[1]
    if address in _NAT64_PREFIX:
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def is_public_address(address: Address) -> bool:
    """Whether the service may connect to this address.

    Deny by default: anything the interpreter does not consider globally
    routable is refused, and an IPv6 form is judged by the IPv4 address it
    embeds.
    """
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
        or not address.is_global
    ):
        return False
    if isinstance(address, ipaddress.IPv4Address) and (
        address in _SHARED_ADDRESS_SPACE
    ):
        return False
    embedded = _embedded_ipv4(address)
    if embedded is not None:
        return is_public_address(embedded)
    return True


def _allowed_address(address: Address) -> str:
    if not is_public_address(address):
        raise AddressNotAllowedError(f"{address} is not a public address")
    return str(address)


async def resolve_host(host: str) -> list[str]:
    """The system resolver, shared with the scan target policy."""
    results = await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )
    return list(dict.fromkeys(str(address[0]) for _, _, _, _, address in results))


async def resolve_public_address(
    host: str,
    *,
    resolver: Resolver | None = None,
    resolution_timeout: float = RESOLUTION_TIMEOUT_SECONDS,
) -> str:
    """The single validated address the caller must connect to.

    Every resolved address has to pass the policy: a name that answers with a
    mixture of public and internal addresses is refused, so the caller never
    has to trust the order the resolver returned.
    """
    if is_ip_literal(host):
        return _allowed_address(ipaddress.ip_address(host))

    try:
        async with asyncio.timeout(resolution_timeout):
            resolved = await (resolver or resolve_host)(host)
    except TimeoutError as exc:
        raise AddressResolutionError(f"{host} did not resolve in time") from exc
    except socket.gaierror as exc:
        raise AddressResolutionError(f"{host} did not resolve") from exc
    if not resolved:
        raise AddressResolutionError(f"{host} did not resolve")

    validated: list[str] = []
    for value in resolved:
        if not is_ip_literal(value):
            raise AddressNotAllowedError(f"{value} is not an address")
        validated.append(_allowed_address(ipaddress.ip_address(value)))
    return validated[0]
