"""Build a constant Nmap profile, never accepting user-supplied flags.

The fixed allowlist and the target separator guard against argument injection;
only validated IP or network literals may follow the separator.
"""

from __future__ import annotations

import ipaddress

from app.modules.scans.targets import ScanTarget

NMAP_PROFILE: tuple[str, ...] = (
    "--privileged",
    "--host-timeout",
    "55m",
    "--script-timeout",
    "5m",
    "-sS",
    "-sU",
    "--top-ports",
    "1000",
    "-sV",
    "-O",
    "--script=vuln",
    "-oX",
    "-",
)

# XML scaninfo types required by the -sS / -sU profile.
REQUIRED_SCAN_TYPES: frozenset[str] = frozenset({"syn", "udp"})


def build_nmap_command(target: ScanTarget, *, nmap_path: str = "nmap") -> list[str]:
    """Build argv without execution, defensively rejecting unsafe literals."""
    if not nmap_path or "\x00" in nmap_path:
        raise ValueError("invalid Nmap binary path")
    if not target.addresses:
        raise ValueError("scan target requires at least one address")
    for address in target.addresses:
        if (
            address.startswith("-")
            or "\x00" in address
            or any(character.isspace() for character in address)
        ):
            raise ValueError("invalid scan address")
        try:
            ipaddress.ip_address(address)
        except ValueError:
            try:
                ipaddress.ip_network(address, strict=False)
            except ValueError as exc:
                raise ValueError(
                    "scan address must be an IP or network literal"
                ) from exc
    families = split_by_family(target)
    if len(families) > 1:
        raise ValueError("scan target mixes address families")
    ipv6 = ipaddress.ip_network(target.addresses[0], strict=False).version == 6
    return [
        nmap_path,
        *NMAP_PROFILE,
        *(["-6"] if ipv6 else []),
        "--",
        *target.addresses,
    ]


def split_by_family(target: ScanTarget) -> list[ScanTarget]:
    """Group validated literals by family, retaining metadata and address order."""
    groups: dict[int, list[str]] = {4: [], 6: []}
    for address in target.addresses:
        groups[ipaddress.ip_network(address, strict=False).version].append(address)
    return [
        ScanTarget(target.asset_type, target.original, tuple(addresses))
        for addresses in groups.values()
        if addresses
    ]
