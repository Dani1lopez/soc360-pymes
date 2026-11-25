"""H2-T6: the DNS TXT and HTTP file challenges, and the resolved fingerprint.

Every network call is injected, so these tests never touch DNS or the web.
"""

from __future__ import annotations

from functools import partial

import httpx
import pytest

from app.modules.assets.ownership.verifiers import (
    MAX_CHALLENGE_BODY_BYTES,
    challenge_name,
    challenge_url,
    fetch_well_known_file,
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


def _public_resolver(addresses: list[str]):
    async def resolver(host: str) -> list[str]:
        return addresses

    return resolver


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value,resolved",
    [
        ("http://127.0.0.1/app", ["127.0.0.1"]),
        ("http://169.254.169.254/latest/meta-data", ["169.254.169.254"]),
        ("http://10.0.0.5/app", ["10.0.0.5"]),
        ("http://[::1]/app", ["::1"]),
        ("http://internal.example/app", ["10.0.0.7"]),
        ("http://attacker.example/app", ["93.184.216.34", "127.0.0.1"]),
    ],
)
async def test_the_http_challenge_never_requests_a_forbidden_address(
    value: str, resolved: list[str]
) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(200, content=b"soc360-verify=token-123")

    fetch = partial(
        fetch_well_known_file,
        resolver=_public_resolver(resolved),
        transport=httpx.MockTransport(handler),
    )

    assert await verify_http_file("web_app", value, "token-123", fetch=fetch) is False
    assert requested == []


@pytest.mark.asyncio
async def test_the_http_challenge_connects_to_the_validated_address() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["header"] = request.headers["host"]
        seen["path"] = request.url.path
        return httpx.Response(200, content=b"soc360-verify=token-123\n")

    fetch = partial(
        fetch_well_known_file,
        resolver=_public_resolver(["93.184.216.34"]),
        transport=httpx.MockTransport(handler),
    )

    assert (
        await verify_http_file(
            "web_app", "http://challenge.example:8080/app", "token-123", fetch=fetch
        )
        is True
    )
    assert seen["host"] == "93.184.216.34"
    assert seen["header"] == "challenge.example:8080"
    assert seen["path"] == "/.well-known/soc360-verify.txt"


@pytest.mark.asyncio
async def test_the_https_challenge_keeps_the_tls_server_name() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, content=b"soc360-verify=token-123")

    fetch = partial(
        fetch_well_known_file,
        resolver=_public_resolver(["93.184.216.34"]),
        transport=httpx.MockTransport(handler),
    )

    assert (
        await verify_http_file(
            "web_app", "https://tls.example/app", "token-123", fetch=fetch
        )
        is True
    )
    assert seen["host"] == "93.184.216.34"
    assert seen["sni"] == "tls.example"


@pytest.mark.asyncio
async def test_the_http_challenge_accepts_a_body_at_the_limit() -> None:
    body = b"soc360-verify=token-123"
    body += b"x" * (MAX_CHALLENGE_BODY_BYTES - len(body))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    fetch = partial(
        fetch_well_known_file,
        resolver=_public_resolver(["93.184.216.34"]),
        transport=httpx.MockTransport(handler),
    )

    assert (
        await verify_http_file("domain", "example.com", "token-123", fetch=fetch)
        is True
    )


@pytest.mark.asyncio
async def test_the_http_challenge_stops_reading_past_the_limit() -> None:
    chunk = b"x" * 8192
    total_chunks = 16
    consumed = 0

    async def chunks():
        nonlocal consumed
        for _ in range(total_chunks):
            consumed += 1
            yield chunk

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=chunks())

    fetch = partial(
        fetch_well_known_file,
        resolver=_public_resolver(["93.184.216.34"]),
        transport=httpx.MockTransport(handler),
    )

    assert (
        await verify_http_file("domain", "example.com", "token-123", fetch=fetch)
        is False
    )
    assert consumed < total_chunks


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
