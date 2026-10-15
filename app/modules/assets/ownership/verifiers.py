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

from app.modules.scans.targets import Resolver, resolve_scan_target

TxtLookup = Callable[[str], Awaitable[list[str]]]
HttpFetch = Callable[[str], Awaitable[str]]

# The challenge lives under a reserved prefix and a well-known path, so a domain
# owner publishes it without touching the service itself.
CHALLENGE_PREFIX = "_soc360-verify"
CHALLENGE_PATH = "/.well-known/soc360-verify.txt"
CHALLENGE_VALUE_PREFIX = "soc360-verify="
HTTP_TIMEOUT_SECONDS = 10.0


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


async def fetch_well_known_file(url: str) -> str:
    """The real challenge fetch, exposed so the router can inject it.

    Redirects are deliberately not followed: the token must be published on the
    target itself, and following one would let the challenge be answered from a
    host the caller does not control.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
    response.raise_for_status()
    return response.text


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
    """Whether the well-known file's body contains the token."""
    try:
        body = await (fetch or fetch_well_known_file)(challenge_url(asset_type, value))
    except (OSError, dns.exception.DNSException, httpx.HTTPError):
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
