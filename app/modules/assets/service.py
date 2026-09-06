"""Asset service: module-level async functions implementing CRUD.

The slice follows the F1 pattern of standalone ``async def`` functions
that take ``AsyncSession`` and ``EventBus`` explicitly. There is no
service class with mutable state. This makes the service trivially
testable with ``AsyncMock`` (T10.3) and avoids hidden globals that
complicate lifecycle management.

Design anchors:
* D-002 — service is async, dependencies are explicit;
* D-004 — per-type semantic validation lives here, not in the schemas;
* D-005 — event snapshot is captured after ``flush`` and only published
  once ``await db.commit()`` succeeds;
* D-007 — when ``tenant_id is not None`` the predicate
  ``Asset.tenant_id == tenant_id`` is added to every query; when
  ``tenant_id is None`` (superadmin route) the predicate is omitted;
* D-008 — pagination is ``count(*)`` + items ordered
  ``created_at DESC, id DESC``.
"""

from __future__ import annotations

import ipaddress
import re
import uuid
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import HttpUrl
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.event_bus import EventBus
from app.event_schemas import (
    AssetCreatedEvent,
    AssetDeletedEvent,
    AssetUpdatedEvent,
)
from app.modules.assets.models import Asset
from app.modules.assets.schemas import (
    AssetCreateRequest,
    AssetUpdate,
)

__all__ = [
    "AssetDuplicateError",
    "_validate_asset_value",
    "create_asset",
    "delete_asset",
    "get_asset",
    "list_assets",
    "update_asset",
]


# Asset stream key — declared in one place so the router and the service
# cannot drift apart. Per design D-005 the slice publishes all three asset
# events onto this single stream.
ASSET_EVENTS_STREAM: Literal["asset.events"] = "asset.events"


# Canonical constraint name used to detect duplicate-tenant/value collisions
# against the alembic-mandated unique index ``uq_assets_tenant_type_value``.
_UNIQUE_CONSTRAINT_NAME = "uq_assets_tenant_type_value"


class AssetDuplicateError(Exception):
    """Raised when an INSERT/UPDATE collides with the unique constraint
    ``uq_assets_tenant_type_value``. The router maps this to HTTP 409.
    """


# ---------------------------------------------------------------------------
# T4.2 — Per-type semantic validation
# ---------------------------------------------------------------------------
# FQDN regex (per-label RFC-1035-ish). Each label is 1–63 chars, must start
# and end with an alphanumeric char, may contain ``-`` in the middle.
_FQDN_LABEL_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
_FQDN_FULL_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
)

# Hostname regex — RFC-1123-like but allows single-label hostnames too.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$"
)

# AWS ARN — at least six colon-separated segments; the resource segment
# (after the last colon) MUST be non-empty. Allows ``arn:aws:s3:::my-bucket``.
_ARN_RE = re.compile(r"^arn:[^:]+:[^:]+:[^:]*:[^:]*:.+$")


def _validate_asset_value(asset_type: str, value: str) -> str:
    """Return the canonicalized value for ``asset_type`` or raise ValueError.

    The error messages are contract-defined (design.md D-004) and the
    router translates them verbatim into a 422 response.
    """

    if asset_type == "ip":
        try:
            return str(ipaddress.ip_address(value))
        except (ValueError, TypeError) as exc:
            raise ValueError("value must be a valid IPv4 or IPv6 address") from exc

    if asset_type == "domain":
        v = value.strip().rstrip(".").lower()
        if not v or not _FQDN_FULL_RE.match(v):
            raise ValueError("value must be a valid FQDN")
        # Per-label sanity (defence-in-depth alongside the overall regex).
        for label in v.split("."):
            if not _FQDN_LABEL_RE.match(label):
                raise ValueError("value must be a valid FQDN")
        return v

    if asset_type == "hostname":
        v = value.strip().lower()
        if not v or not _HOSTNAME_RE.match(v):
            raise ValueError("value must be a valid hostname")
        return v

    if asset_type == "web_app":
        try:
            parsed = HttpUrl(value)
        except Exception as exc:
            raise ValueError("value must be a valid http(s) URL") from exc
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise ValueError("value must be a valid http(s) URL")
        return str(parsed)

    if asset_type == "subnet":
        try:
            network = ipaddress.ip_network(value, strict=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("value must be a valid CIDR") from exc
        # canonical "compressed" CIDR — drops host bits.
        return str(network)

    if asset_type == "cloud_resource":
        v = value.strip()
        if not _ARN_RE.match(v):
            raise ValueError("value must be a valid ARN")
        return v

    # Unknown asset_type: surface as 422 rather than letting it propagate.
    raise ValueError(f"unknown asset type: {asset_type!r}")


# ---------------------------------------------------------------------------
# Helpers — private
# ---------------------------------------------------------------------------
def _add_tenant_predicate(
    stmt: Any,
    tenant_id: uuid.UUID | None,
) -> Any:
    """Apply the tenant predicate when ``tenant_id`` is not None.

    Callers (service and tests) use this so the predicate logic is in one
    place. When ``tenant_id is None`` (superadmin route) the predicate is
    intentionally absent — RLS still applies via the auth-time
    ``set_tenant_context`` and the WHERE-less query is safe.
    """
    if tenant_id is not None:
        return stmt.where(Asset.tenant_id == tenant_id)
    return stmt


def _public_field_names() -> tuple[Literal["type"], Literal["value"]]:
    """Canonical ordering of public, mutable field names on the asset.

    The PATCH handler computes ``changed_fields`` by intersecting this
    list with the user-supplied update keys, preserving the order.
    """
    return ("type", "value")


def _is_duplicate_constraint_error(exc: IntegrityError) -> bool:
    """Detect a uq_assets_tenant_type_value violation robustly across drivers."""
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False
    name = (
        getattr(orig, "constraint_name", None)
        or getattr(orig, "diag", None)
        and getattr(orig.diag, "constraint_name", None)
    )
    if name and _UNIQUE_CONSTRAINT_NAME in str(name):
        return True
    # Fallback: search the asyncpg message string for the constraint name.
    msg = str(orig)
    return _UNIQUE_CONSTRAINT_NAME in msg


# ---------------------------------------------------------------------------
# T4.1 + T4.5 — CRUD functions
# ---------------------------------------------------------------------------
async def create_asset(
    data: AssetCreateRequest,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Asset:
    """Create a new asset, persist + publish ``asset.created``.

    Performs:
      1. semantic value validation (``_validate_asset_value``);
      2. INSERT + ``flush`` (so the unique-constraint check fires here);
      3. ``commit``;
      4. publish ``AssetCreatedEvent`` on ``asset.events`` only AFTER
         commit succeeds.

    Other :class:`sqlalchemy.exc.IntegrityError` propagate.
    """
    # data.value is the PUBLIC field; we re-validate against the supplied
    # discriminator (e.g. data.type == "ip").
    canonical_value = _validate_asset_value(data.type, data.value)

    asset = Asset(
        tenant_id=tenant_id,
        asset_type=data.type,
        value=canonical_value,
    )
    db.add(asset)
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_duplicate_constraint_error(exc):
            # No manual rollback — the session's outer transaction context
            # manager reclaims the failing connection.
            raise AssetDuplicateError(
                f"asset with type={data.type!r}, value={canonical_value!r} "
                "already exists for this tenant"
            ) from exc
        raise

    await db.commit()
    # Capture-after-flush / publish-after-commit invariant (D-005).
    event = AssetCreatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        asset_id=asset.id,
        type=data.type,  # type: ignore[arg-type]
        value=canonical_value,
        created_at=asset.created_at,
    )
    await event_bus.publish(event, stream=ASSET_EVENTS_STREAM)
    return asset


async def get_asset(
    asset_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> Asset | None:
    """Return the asset or None.

    When ``tenant_id is not None``, the query is scoped to that tenant.
    When ``tenant_id is None``, the query has no WHERE clause and RLS
    decides visibility.
    """
    stmt = select(Asset).where(Asset.id == asset_id)
    stmt = _add_tenant_predicate(stmt, tenant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_assets(
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
) -> tuple[Sequence[Asset], int]:
    """Return ``(items, total)`` ordered by ``created_at DESC, id DESC``.

    The router calls this function for the paginated list endpoint. For
    CSV export a separate, unpaginated query is issued by the router
    directly against ``Asset`` to stream rows without holding a list in
    memory.
    """
    base_stmt = _add_tenant_predicate(select(Asset), tenant_id)
    count_stmt = _add_tenant_predicate(
        select(func.count()).select_from(Asset), tenant_id
    )
    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = (
        base_stmt.order_by(Asset.created_at.desc(), Asset.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_stmt)).scalars().all()
    return items, int(total or 0)


async def update_asset(
    asset_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    data: AssetUpdate,
    db: AsyncSession,
    event_bus: EventBus,
) -> Asset | None:
    """Apply a partial update; return the updated asset or None.

    Returns ``None`` when the asset does not exist in the visible scope
    (router maps to 404). The semantic value is computed against the
    *effective* pair ``(effective_type, effective_value)`` so partial
    changes still go through the type-specific validator.

    Only after the DB commit succeeds is the ``asset.updated`` event
    published.
    """
    stmt = _add_tenant_predicate(
        select(Asset).where(Asset.id == asset_id),
        tenant_id,
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        return None

    update_data = data.model_dump(exclude_unset=True)
    changed_fields: list[str] = []
    for public_name in _public_field_names():
        if public_name not in update_data:
            continue
        new_value = update_data[public_name]
        if public_name == "type":
            if new_value != asset.asset_type:
                asset.asset_type = new_value
                changed_fields.append("type")
        elif public_name == "value":
            if new_value != asset.value:
                asset.value = new_value
                changed_fields.append("value")

    # Validate the effective pair so we catch semantically invalid
    # combinations (e.g. "192.168.0.0/40" passed as a "subnet" value).
    _validate_asset_value(asset.asset_type, asset.value)

    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_duplicate_constraint_error(exc):
            raise AssetDuplicateError(
                "update would produce a duplicate (tenant_id, type, value)"
            ) from exc
        raise

    await db.commit()

    event = AssetUpdatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        changed_fields=changed_fields,
    )
    await event_bus.publish(event, stream=ASSET_EVENTS_STREAM)
    return asset


async def delete_asset(
    asset_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    event_bus: EventBus,
) -> bool:
    """Delete the asset (tenant-scoped); return True on success, False on miss.

    On success, publishes ``asset.deleted`` on ``asset.events`` only AFTER
    commit succeeds.
    """
    stmt = _add_tenant_predicate(
        select(Asset).where(Asset.id == asset_id),
        tenant_id,
    )
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        return False

    captured_id = asset.id
    captured_tenant = asset.tenant_id

    await db.delete(asset)
    await db.commit()

    event = AssetDeletedEvent(
        event_id=uuid.uuid4(),
        tenant_id=captured_tenant,
        asset_id=captured_id,
    )
    await event_bus.publish(event, stream=ASSET_EVENTS_STREAM)
    return True
