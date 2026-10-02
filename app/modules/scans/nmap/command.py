"""Build a constant Nmap profile, never accepting user-supplied flags.

The fixed allowlist and the target separator guard against argument injection;
only validated IP or network literals may follow the separator.
"""

from __future__ import annotations

import ipaddress

from app.modules.scans.targets import ScanTarget

NMAP_PROFILE: tuple[str, ...] = (
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
    return [nmap_path, *NMAP_PROFILE, "--", *target.addresses]
