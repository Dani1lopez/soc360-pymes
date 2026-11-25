"""Production target policy (H2-T1, decision D2=A).

Only RFC1918/ULA private networks are scannable, and the policy must not depend
on the local demo switch: a deployment with SCAN_DEMO_MODE on must not widen it.
"""

import pytest

from app.core.config import settings
from app.modules.scans.targets import (
    ScanTarget,
    TargetRejectedError,
    resolve_scan_target,
)

PUBLIC_ADDRESSES = ["8.8.8.8", "2606:4700:4700::1111"]
PRIVATE_ADDRESSES = ["10.0.0.5", "172.18.0.7", "192.168.1.10", "fc00::1", "fd00::5"]
# Loopback, link-local, multicast, unspecified, reserved, CGNAT, documentation,
# benchmarking and IPv6 transition forms are never scannable.
NOT_ALLOWED_ADDRESSES = [
    "127.0.0.1",
    "::1",
    "169.254.169.254",
    "224.0.0.1",
    "ff02::1",
    "0.0.0.0",
    "::",
    "fe80::1",
    "240.0.0.1",
    "100.64.0.1",
    "192.0.2.1",
    "198.51.100.7",
    "203.0.113.5",
    "198.18.0.1",
    "2001:db8::1",
    "::ffff:10.0.0.5",
    "2002:7f00:1::1",
    "64:ff9b::a9fe:a9fe",
    "2001:0:4136:e378::1",
]


@pytest.fixture(params=[False, True], ids=["production", "demo"])
def demo_mode(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> bool:
    monkeypatch.setattr(settings, "SCAN_DEMO_MODE", request.param)
    return bool(request.param)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", PUBLIC_ADDRESSES)
async def test_public_address_is_not_allowed(demo_mode: bool, address: str) -> None:
    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("ip", address)
    assert caught.value.reason == "target_not_allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("address", PRIVATE_ADDRESSES)
async def test_private_address_is_allowed(demo_mode: bool, address: str) -> None:
    assert (await resolve_scan_target("ip", address)).addresses == (address,)


@pytest.mark.asyncio
@pytest.mark.parametrize("address", NOT_ALLOWED_ADDRESSES)
async def test_forbidden_address_is_not_allowed(demo_mode: bool, address: str) -> None:
    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("ip", address)
    assert caught.value.reason == "target_not_allowed"


@pytest.mark.asyncio
async def test_private_subnet_is_allowed_in_both_modes(demo_mode: bool) -> None:
    target = await resolve_scan_target("subnet", "172.18.0.0/24")
    assert target == ScanTarget("subnet", "172.18.0.0/24", ("172.18.0.0/24",))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    ["8.8.8.0/24", "192.0.2.0/24", "172.15.255.0/24", "2001:db8::/120"],
)
async def test_non_private_subnet_is_not_allowed(demo_mode: bool, value: str) -> None:
    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("subnet", value)
    assert caught.value.reason == "target_not_allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["8.8.8.0/23", "0.0.0.0/0", "10.0.0.0/8"])
async def test_oversized_subnet_is_rejected_before_policy(
    demo_mode: bool, value: str
) -> None:
    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("subnet", value)
    assert caught.value.reason == "target_too_large"


@pytest.mark.asyncio
async def test_resolved_public_hostname_is_not_allowed(demo_mode: bool) -> None:
    async def resolver(host: str) -> list[str]:
        return ["8.8.8.8", "10.0.0.1"]

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("hostname", "example.com", resolver=resolver)
    assert caught.value.reason == "target_not_allowed"


@pytest.mark.asyncio
async def test_resolved_private_hostname_is_allowed(demo_mode: bool) -> None:
    async def resolver(host: str) -> list[str]:
        return ["10.0.0.7"]

    target = await resolve_scan_target(
        "hostname", "intranet.example", resolver=resolver
    )
    assert target.addresses == ("10.0.0.7",)
