"""H2-T6: the DNS TXT and HTTP file challenges, and the resolved fingerprint.

Every network call is injected, so these tests never touch DNS or the web.
"""

from __future__ import annotations

import pytest

from app.modules.assets.ownership.verifiers import (
    challenge_name,
    challenge_url,
    target_fingerprint,
    verify_dns_txt,
    verify_http_file,
)


@pytest.mark.parametrize(
    "asset_type,value,expected",
    [
        ("domain", "example.com", "_soc360-verify.example.com"),
        ("hostname", "intranet.example", "_soc360-verify.intranet.example"),
        ("web_app", "https://app.example/path", "_soc360-verify.app.example"),
    ],
)
def test_the_challenge_name_is_under_a_reserved_prefix(
    asset_type: str, value: str, expected: str
) -> None:
    assert challenge_name(asset_type, value) == expected


@pytest.mark.parametrize(
    "asset_type,value,expected",
    [
        (
            "domain",
            "example.com",
            "https://example.com/.well-known/soc360-verify.txt",
        ),
        (
            "web_app",
            "http://10.0.0.4/path",
            "http://10.0.0.4/.well-known/soc360-verify.txt",
        ),
    ],
)
def test_the_challenge_url_is_the_well_known_file(
    asset_type: str, value: str, expected: str
) -> None:
    assert challenge_url(asset_type, value) == expected


@pytest.mark.asyncio
async def test_dns_txt_accepts_a_record_containing_the_token() -> None:
    async def lookup(name: str) -> list[str]:
        assert name == "_soc360-verify.example.com"
        return ["unrelated", "soc360-verify=token-123"]

    assert (
        await verify_dns_txt("domain", "example.com", "token-123", lookup=lookup)
        is True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("records", [[], ["soc360-verify=someone-else"]])
async def test_dns_txt_rejects_a_missing_token(records: list[str]) -> None:
    async def lookup(name: str) -> list[str]:
        return records

    assert (
        await verify_dns_txt("domain", "example.com", "token-123", lookup=lookup)
        is False
    )


@pytest.mark.asyncio
async def test_dns_txt_treats_a_lookup_failure_as_unverified() -> None:
    async def lookup(name: str) -> list[str]:
        raise TimeoutError("no answer")

    assert (
        await verify_dns_txt("domain", "example.com", "token", lookup=lookup) is False
    )


@pytest.mark.asyncio
async def test_http_file_accepts_the_token_in_the_body() -> None:
    async def fetch(url: str) -> str:
        assert url == "https://example.com/.well-known/soc360-verify.txt"
        return "soc360-verify=token-123\n"

    assert (
        await verify_http_file("domain", "example.com", "token-123", fetch=fetch)
        is True
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["", "soc360-verify=someone-else\n"])
async def test_http_file_rejects_a_missing_token(body: str) -> None:
    async def fetch(url: str) -> str:
        return body

    assert (
        await verify_http_file("domain", "example.com", "token-123", fetch=fetch)
        is False
    )


@pytest.mark.asyncio
async def test_http_file_treats_a_fetch_failure_as_unverified() -> None:
    async def fetch(url: str) -> str:
        raise ConnectionError("refused")

    assert (
        await verify_http_file("domain", "example.com", "token", fetch=fetch) is False
    )


@pytest.mark.asyncio
async def test_the_fingerprint_is_the_resolved_addresses() -> None:
    async def resolver(host: str) -> list[str]:
        assert host == "intranet.example"
        return ["10.0.0.7", "fd00::1"]

    assert (
        await target_fingerprint("hostname", "intranet.example", resolver=resolver)
        == "10.0.0.7,fd00::1"
    )


@pytest.mark.asyncio
async def test_the_fingerprint_of_an_address_is_itself() -> None:
    assert await target_fingerprint("ip", "10.0.0.5") == "10.0.0.5"
