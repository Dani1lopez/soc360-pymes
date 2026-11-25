"""Scan-time target gates, without DNS or process execution.

The private-network policy itself lives in ``test_target_policy.py``; this module
covers syntax canonicalization, resolution mechanics and stable failure reasons.
"""

import asyncio
import socket
from dataclasses import FrozenInstanceError

import pytest

from app.modules.scans.targets import (
    ScanTarget,
    TargetRejectedError,
    resolve_scan_target,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["10.0.0.4", "fd00::1111"])
async def test_private_ip(value: str) -> None:
    target = await resolve_scan_target("ip", value)
    assert target == ScanTarget("ip", value, (value,))
    with pytest.raises(FrozenInstanceError):
        setattr(target, "original", "changed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_type,value,reason",
    [
        ("subnet", "10.0.0.0/8", "target_too_large"),
        ("subnet", "0.0.0.0/0", "target_too_large"),
        ("subnet", "fc00::/119", "target_too_large"),
        ("cloud_resource", "arn:aws:s3:::bucket", "target_unsupported_type"),
        ("unknown", "whatever", "target_unsupported_type"),
        ("hostname", "-oX /tmp/x", "target_invalid"),
        ("ip", "10.0.0.4 --script exploit", "target_invalid"),
        ("web_app", "not a url", "target_invalid"),
    ],
)
async def test_rejected(asset_type: str, value: str, reason: str) -> None:
    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target(asset_type, value)
    assert caught.value.reason == reason
    assert len(caught.value.reason) <= 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,canonical",
    [
        ("10.0.0.42/24", "10.0.0.0/24"),
        ("fd00::42/120", "fd00::/120"),
    ],
)
async def test_private_subnet(value: str, canonical: str) -> None:
    target = await resolve_scan_target("subnet", value)
    assert target.addresses == (canonical,)
    assert target.original == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_type,value,host",
    [
        ("hostname", " INTRANET.EXAMPLE ", "intranet.example"),
        ("domain", "INTRANET.EXAMPLE.", "intranet.example"),
        ("web_app", "https://intranet.example/path", "intranet.example"),
    ],
)
async def test_resolved_addresses(asset_type: str, value: str, host: str) -> None:
    calls: list[str] = []

    async def resolver(name: str) -> list[str]:
        calls.append(name)
        return ["10.0.0.4", "fd00::1111"]

    target = await resolve_scan_target(asset_type, value, resolver=resolver)
    assert calls == [host]
    assert target.addresses == ("10.0.0.4", "fd00::1111")
    assert target.original == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses,reason",
    [
        ([], "target_unresolvable"),
        (["not-an-ip"], "target_invalid"),
    ],
)
async def test_bad_resolution(addresses: list[str], reason: str) -> None:
    async def resolver(host: str) -> list[str]:
        return addresses

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("hostname", "intranet.example", resolver=resolver)
    assert caught.value.reason == reason
    assert len(reason) <= 64


@pytest.mark.asyncio
async def test_dns_failure() -> None:
    async def resolver(host: str) -> list[str]:
        raise socket.gaierror("DNS failed")

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("hostname", "intranet.example", resolver=resolver)
    assert caught.value.reason == "target_unresolvable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,ip",
    [
        ("https://10.0.0.4/path", "10.0.0.4"),
        ("https://[fd00::1111]/", "fd00::1111"),
    ],
)
async def test_url_literal_never_resolved(url: str, ip: str) -> None:
    async def resolver(host: str) -> list[str]:
        pytest.fail("IP literals must not use DNS")

    assert (await resolve_scan_target("web_app", url, resolver=resolver)).addresses == (
        ip,
    )


async def test_hanging_resolver_is_bounded() -> None:
    async def resolver(host: str) -> list[str]:
        await asyncio.sleep(30)
        return ["10.0.0.7"]

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target(
            "hostname",
            "intranet.example",
            resolver=resolver,
            resolution_timeout=0.05,
        )
    assert caught.value.reason == "target_resolution_timeout"
