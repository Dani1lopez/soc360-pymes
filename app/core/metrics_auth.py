"""PR4 #260 — Metrics endpoint authentication primitives.

Lives outside ``app/main.py`` so the route stays a thin caller and the 4-step
extraction pipeline + bitwise ``|`` compare are independently unit-testable.

Contract (design rev 16):
- ``METRICS_TOKEN_HEADER`` is the only accepted header (``x-metrics-token``).
- ``METRICS_TOKEN_MAX_BYTES`` caps the header at 256 **wire-level** bytes
  (latin-1 round-trip — see Implementation Refinements §2 in design rev 16)
  BEFORE any whitespace scan (perf protection vs. oversized whitespace payload).
- ``_extract_header`` runs 4 steps in this order
  (cheap-before-expensive — see Implementation Refinements §4 in design rev 16):
    1. duplicate-header rejection (RFC 7230 §3.2.2)
    2. latin-1 wire-level byte cap
    3. ``isascii()`` rejection (covers surrogates + Latin-1 supplement in one
       O(n) no-alloc pass — strictly stronger than ``strict UTF-8 encode``,
       see Implementation Refinements §3)
    4. whitespace rejection (NOT ``.strip()`` normalization)
- ``verify_metrics_token`` uses bitwise ``|`` on ``hmac.compare_digest`` to
  force both compares to always execute (no short-circuit), satisfying the
  spec's "either authenticates during overlap" semantics.
- ``_current_bytes`` / ``_previous_bytes`` are ``@lru_cache(maxsize=1)``
  primed eagerly by ``app.main.create_app`` (see app/main.py; the original
  ``Settings.model_post_init`` location was abandoned to break the
  ``config ↔ metrics_auth`` import cycle — see Implementation Refinements §1).
- ``_unauthorized_response`` returns a 401 JSON body with no diagnostic detail.
"""
from __future__ import annotations

import hmac
from functools import lru_cache
from typing import Any

from fastapi.responses import JSONResponse


def _get_settings():
    """Lazy import to break the ``config`` ↔ ``metrics_auth`` cycle.

    Reading ``settings`` via a function-local import is safe because by the
    time any HTTP request lands (or any test fixture runs), both modules are
    fully initialised.
    """
    from app.core.config import settings

    return settings


METRICS_TOKEN_HEADER: str = "x-metrics-token"
METRICS_TOKEN_MAX_BYTES: int = 256


def _extract_header(request: Any) -> str:
    """Return the presented ``X-Metrics-Token`` value, or ``""`` on any anomaly.

    4-step pipeline:

    1. RFC 7230 §3.2.2 — duplicate-header rejection (``getlist() != 1``).
    2. Byte cap BEFORE whitespace scan; ``latin-1`` round-trip recovers the
       wire-level byte length after Starlette's latin-1 header decode.
    3. Whitespace rejection (NOT ``.strip()`` normalization — silent
       normalization was the prior flaw).
    4. ``isascii()`` rejects non-ASCII chars (raw bytes that were never valid
       UTF-8) and surrogate code points.
    """
    raw_values = request.headers.getlist(METRICS_TOKEN_HEADER)
    if len(raw_values) != 1:
        return ""

    value = raw_values[0]

    # Step 2 — byte cap from the wire-level byte length.
    try:
        wire_bytes = value.encode("latin-1", errors="strict")
    except UnicodeEncodeError:
        return ""
    if len(wire_bytes) > METRICS_TOKEN_MAX_BYTES:
        return ""

    # Step 4 — non-ASCII + surrogate rejection.
    if not value.isascii():
        return ""

    # Step 3 — whitespace rejection (NOT normalization).
    if value != value.strip() or any(c.isspace() for c in value):
        return ""

    return value


@lru_cache(maxsize=1)
def _current_bytes() -> bytes:
    """Encoded current token candidate; eagerly primed by ``create_app``.

    Returns ``b""`` when ``settings.METRICS_TOKEN`` is ``None`` so non-prod
    with no configured token always returns ``False`` from
    ``verify_metrics_token``.
    """
    live_settings = _get_settings()
    if live_settings.METRICS_TOKEN is None:
        return b""
    return live_settings.METRICS_TOKEN.get_secret_value().encode("utf-8")


@lru_cache(maxsize=1)
def _previous_bytes() -> bytes:
    """Encoded previous token candidate (rotation overlap); see ``_current_bytes``."""
    live_settings = _get_settings()
    if live_settings.METRICS_TOKEN_PREVIOUS is None:
        return b""
    return live_settings.METRICS_TOKEN_PREVIOUS.get_secret_value().encode("utf-8")


def verify_metrics_token(presented: str) -> bool:
    """Bitwise-``|`` compare over current and previous (NOT short-circuiting).

    Both ``hmac.compare_digest`` calls always execute; the combinator is
    ``|`` (not ``&`` and not Python's short-circuiting ``or``) so the spec's
    "either credential authenticates during overlap" semantics is preserved.
    """
    if presented == "":
        return False
    presented_bytes = presented.encode("utf-8")
    current_match = hmac.compare_digest(presented_bytes, _current_bytes())
    previous_match = hmac.compare_digest(presented_bytes, _previous_bytes())
    return current_match | previous_match


def _unauthorized_response() -> JSONResponse:
    """Return a 401 with ``{"detail": "unauthorized"}``.

    Each call returns a new instance but every instance serialises to the
    same bytes — verified by ``test_two_calls_are_byte_identical``. This is
    the canonical generic 401 endpoint: no reason-specific detail, no
    token material, no diagnostic path.
    """
    return JSONResponse(status_code=401, content={"detail": "unauthorized"})
