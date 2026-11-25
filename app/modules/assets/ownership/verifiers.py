"""Ownership challenges: DNS TXT, HTTP file, and the resolved fingerprint.

Network access sits behind injectable callables, so the service and the tests
can supply their own resolver and fetcher. The real implementations use
dnspython for TXT records and httpx for the well-known file.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import dns.asyncresolver
import dns.exception
import httpx

from app.core.net_policy import (
    AddressNotAllowedError,
    is_ip_literal,
    resolve_public_address,
)
from app.modules.scans.targets import Resolver, resolve_scan_target

TxtLookup = Callable[[str], Awaitable[list[str]]]
HttpFetch = Callable[[str], Awaitable[str]]

# The challenge lives under a reserved prefix and a well-known path, so a domain
# owner publishes it without touching the service itself.
CHALLENGE_PREFIX = "_soc360-verify"
CHALLENGE_PATH = "/.well-known/soc360-verify.txt"
CHALLENGE_VALUE_PREFIX = "soc360-verify="
HTTP_TIMEOUT_SECONDS = 10.0

# H3/S3: the challenge is a token in a small text file. Reading more than this is
# never needed, and an unbounded read is both a memory and a bandwidth hazard.
MAX_CHALLENGE_BODY_BYTES = 64 * 1024


class ChallengeBodyTooLargeError(ValueError):
    """The published file exceeded the bounded read, so no token can be trusted."""


def _host(asset_type: str, value: str) -> str:
    """The hostname a challenge belongs to: no scheme, no path, no trailing dot."""
    if asset_type == "web_app":
        return urlsplit(value).hostname or ""
    return value.rstrip(".")


def challenge_name(asset_type: str, value: str) -> str:
    """The TXT record the owner publishes the token in."""
    return f"{CHALLENGE_PREFIX}.{_host(asset_type, value)}"


def challenge_url(asset_type: str, value: str) -> str:
    """The file URL the owner publishes the token at.

    A ``web_app`` keeps its own scheme, so an internal HTTP target is verified
    over HTTP; a bare domain is reached over HTTPS.
    """
    if asset_type == "web_app":
        parts = urlsplit(value)
        origin = f"{parts.scheme}://{parts.netloc}"
    else:
        origin = f"https://{_host(asset_type, value)}"
    return f"{origin}{CHALLENGE_PATH}"


async def lookup_txt_records(name: str) -> list[str]:
    """The real TXT lookup, exposed so the router can inject it."""
    answer = await dns.asyncresolver.resolve(name, "TXT")
    return [b"".join(record.strings).decode("utf-8", "replace") for record in answer]


async def fetch_well_known_file(
    url: str,
    *,
    resolver: Resolver | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """The real challenge fetch, exposed so the router can inject it.

    H2/S2: the host is resolved once, the address is validated against the
    outbound policy, and the connection is pinned to that address while the
    ``Host`` header and the TLS server name keep the published name. Redirects
    are deliberately not followed: the token must be published on the target
    itself, and following one would let the challenge be answered from a host
    the caller does not control.

    H3/S3: the body is streamed and read up to ``MAX_CHALLENGE_BODY_BYTES``;
    anything longer fails the challenge instead of being buffered.
    """
    parts = urlsplit(url)
    address = await resolve_public_address(parts.hostname or "", resolver=resolver)
    pinned, headers, extensions = _pinned_request(url, address)
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        transport=transport,
        follow_redirects=False,
    ) as client:
        async with client.stream(
            "GET", pinned, headers=headers, extensions=extensions
        ) as response:
            response.raise_for_status()
            return await _read_bounded_body(response)


def _pinned_request(
    url: str, address: str
) -> tuple[str, dict[str, str], dict[str, object]]:
    """Rewrite the URL to the validated address, keeping the published name.

    The ``Host`` header and, for TLS, the SNI/verification name stay the name the
    owner published, so the server and its certificate still see that name while
    the socket goes to the address that was checked.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port
    default_port = 443 if scheme == "https" else 80

    pinned = f"{scheme}://{f'[{address}]' if ':' in address else address}"
    if port is not None:
        pinned += f":{port}"
    pinned += parts.path or "/"
    if parts.query:
        pinned += f"?{parts.query}"

    headers = {"host": host if port in (None, default_port) else f"{host}:{port}"}
    extensions: dict[str, object] = {}
    if scheme == "https" and not is_ip_literal(host):
        extensions["sni_hostname"] = host
    return pinned, headers, extensions


async def _read_bounded_body(response: httpx.Response) -> str:
    """The decoded body, refusing to buffer more than the challenge limit."""
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body.extend(chunk)
        if len(body) > MAX_CHALLENGE_BODY_BYTES:
            raise ChallengeBodyTooLargeError(
                f"challenge body exceeds {MAX_CHALLENGE_BODY_BYTES} bytes"
            )
    return body.decode("utf-8", "replace")


async def verify_dns_txt(
    asset_type: str,
    value: str,
    token: str,
    *,
    lookup: TxtLookup | None = None,
) -> bool:
    """Whether any TXT record at the challenge name contains the token.

    A lookup failure is a failed challenge, never an exception: the caller is
    deciding whether to authorize a scan, so an unreachable resolver must not
    authorize anything.
    """
    try:
        records = await (lookup or lookup_txt_records)(
            challenge_name(asset_type, value)
        )
    except (OSError, dns.exception.DNSException):
        return False
    return any(token in record for record in records)


async def verify_http_file(
    asset_type: str,
    value: str,
    token: str,
    *,
    fetch: HttpFetch | None = None,
) -> bool:
    """Whether the well-known file's body contains the token.

    A forbidden address, an oversized body, a fetch failure or a broken
    challenge answer is a failed challenge, never an exception: the caller is
    deciding whether to authorize a scan.
    """
    try:
        body = await (fetch or fetch_well_known_file)(challenge_url(asset_type, value))
    except (
        AddressNotAllowedError,
        ChallengeBodyTooLargeError,
        OSError,
        dns.exception.DNSException,
        httpx.HTTPError,
    ):
        return False
    return token in body


async def target_fingerprint(
    asset_type: str, value: str, *, resolver: Resolver | None = None
) -> str:
    """The stable answer ownership was verified against (decision D3).

    Built from the same resolution a scan uses, so the executor can re-resolve,
    compare, and refuse a target whose DNS now points somewhere else.
    """
    target = await resolve_scan_target(asset_type, value, resolver=resolver)
    return ",".join(target.addresses)
