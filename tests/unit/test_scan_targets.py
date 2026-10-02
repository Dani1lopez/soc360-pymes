"""Scan-time target gates, without DNS or process execution."""

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
@pytest.mark.parametrize("value", ["8.8.8.8", "2606:4700:4700::1111"])
async def test_public_ip(value: str) -> None:
    target = await resolve_scan_target("ip", value)
    assert target == ScanTarget("ip", value, (value,))
    with pytest.raises(FrozenInstanceError):
        setattr(target, "original", "changed")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_type,value,reason",
    [
        *(
            ("ip", ip, "target_not_global")
            for ip in [
                "127.0.0.1",
                "10.0.0.1",
                "192.168.1.1",
                "169.254.169.254",
                "100.64.0.1",
                "0.0.0.0",
                "::1",
                "fe80::1",
                "::ffff:127.0.0.1",
            ]
        ),
        ("subnet", "8.8.8.0/23", "target_too_large"),
        ("subnet", "0.0.0.0/0", "target_too_large"),
        ("subnet", "10.0.0.0/24", "target_not_global"),
        ("subnet", "2606:4700:4700::/119", "target_too_large"),
        ("cloud_resource", "arn:aws:s3:::bucket", "target_unsupported_type"),
        ("unknown", "whatever", "target_unsupported_type"),
        ("hostname", "-oX /tmp/x", "target_invalid"),
        ("ip", "8.8.8.8 --script exploit", "target_invalid"),
        ("web_app", "https://127.0.0.1", "target_not_global"),
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
        ("8.8.8.42/24", "8.8.8.0/24"),
        ("2606:4700:4700::42/120", "2606:4700:4700::/120"),
    ],
)
async def test_public_subnet(value: str, canonical: str) -> None:
    target = await resolve_scan_target("subnet", value)
    assert target.addresses == (canonical,)
    assert target.original == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "asset_type,value,host",
    [
        ("hostname", " EXAMPLE.COM ", "example.com"),
        ("domain", "EXAMPLE.COM.", "example.com"),
        ("web_app", "https://example.com/path", "example.com"),
    ],
)
async def test_resolved_addresses(asset_type: str, value: str, host: str) -> None:
    calls: list[str] = []

    async def resolver(name: str) -> list[str]:
        calls.append(name)
        return ["8.8.8.8", "2606:4700:4700::1111"]

    target = await resolve_scan_target(asset_type, value, resolver=resolver)
    assert calls == [host]
    assert target.addresses == ("8.8.8.8", "2606:4700:4700::1111")
    assert target.original == value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses,reason",
    [
        (["8.8.8.8", "10.0.0.1"], "target_not_global"),
        ([], "target_unresolvable"),
        (["not-an-ip"], "target_invalid"),
    ],
)
async def test_bad_resolution(addresses: list[str], reason: str) -> None:
    async def resolver(host: str) -> list[str]:
        return addresses

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("hostname", "example.com", resolver=resolver)
    assert caught.value.reason == reason
    assert len(reason) <= 64


@pytest.mark.asyncio
async def test_dns_failure() -> None:
    async def resolver(host: str) -> list[str]:
        raise socket.gaierror("DNS failed")

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target("hostname", "example.com", resolver=resolver)
    assert caught.value.reason == "target_unresolvable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url,ip",
    [
        ("https://8.8.8.8/path", "8.8.8.8"),
        ("https://[2606:4700:4700::1111]/", "2606:4700:4700::1111"),
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
        return ["93.184.216.34"]

    with pytest.raises(TargetRejectedError) as caught:
        await resolve_scan_target(
            "hostname", "example.com", resolver=resolver, resolution_timeout=0.05
        )
    assert caught.value.reason == "target_resolution_timeout"
