"""Scan service: module-level async functions implementing the Scans CRUD.

Follows the same shape as ``app.modules.assets.service``: standalone
``async def`` functions that take ``AsyncSession`` and ``EventBus`` explicitly,
with no class holding mutable state. That keeps the service testable with plain
mocks and avoids hidden globals.

``_validate_scan_config`` is the semantic frontier for scan configuration. It
is called on POST and again on PATCH against the EFFECTIVE ``(type, config)``
pair, so a partially edited scan can never be persisted in a combination its
type does not allow. Its ``ValueError`` messages are a contract: the router
copies them verbatim into the 422 ``detail``, so they must stay stable.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.event_bus import EventBus
from app.event_schemas import (
    ScanCreatedEvent,
    ScanDeletedEvent,
    ScanUpdatedEvent,
)
from app.modules.scans.models import Scan
from app.modules.scans.schemas import ScanCreateRequest, ScanUpdate

__all__ = [
    "SCAN_EVENTS_STREAM",
    "ScanDuplicateError",
    "_validate_scan_config",
    "create_scan",
    "delete_scan",
    "get_scan",
    "list_scans",
    "update_scan",
]

# The config keys each scan type accepts, in the public order used for
# normalisation. A type not present here is not a valid scan type.
_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "discovery": ("host_discovery",),
    "vulnerability": ("checks",),
    "web": ("paths",),
    "full": ("host_discovery", "checks", "paths"),
}

_CHECKS_MESSAGE = "config.checks must be a non-empty list of non-empty strings"
_PATHS_MESSAGE = "config.paths must be a non-empty list of paths beginning with '/'"


def _validate_scan_config(scan_type: str, config: object) -> dict[str, Any]:
    """Return the normalised config for ``scan_type``, or raise ValueError.

    Enforces the exact key set per type and the per-key value rules. Returns a
    new dict with fresh lists so a caller cannot mutate persisted state through
    the returned object. Never adds defaults: an absent key is an error, not a
    silent default.
    """
    if scan_type not in _CONFIG_KEYS:
        raise ValueError(f"unknown scan_type {scan_type!r}")

    if not isinstance(config, dict):
        raise ValueError(f"config must be an object for scan_type {scan_type!r}")

    allowed = _CONFIG_KEYS[scan_type]
    for key in sorted(config):
        if key not in allowed:
            raise ValueError(f"config.{key} is not allowed for scan_type {scan_type!r}")

    normalised: dict[str, Any] = {}

    if "host_discovery" in allowed:
        if "host_discovery" not in config:
            raise ValueError(
                f"config.host_discovery is required for scan_type {scan_type!r}"
            )
        value = config["host_discovery"]
        if not isinstance(value, bool):
            raise ValueError(
                f"config.host_discovery must be a boolean for scan_type {scan_type!r}"
            )
        normalised["host_discovery"] = value

    if "checks" in allowed:
        if "checks" not in config:
            raise ValueError(f"config.checks is required for scan_type {scan_type!r}")
        checks = config["checks"]
        if (
            not isinstance(checks, list)
            or not checks
            or not all(isinstance(item, str) and item for item in checks)
        ):
            raise ValueError(f"{_CHECKS_MESSAGE} for scan_type {scan_type!r}")
        normalised["checks"] = list(checks)

    if "paths" in allowed:
        if "paths" not in config:
            raise ValueError(f"config.paths is required for scan_type {scan_type!r}")
        paths = config["paths"]
        if (
            not isinstance(paths, list)
            or not paths
            or not all(
                isinstance(item, str) and item.startswith("/") for item in paths
            )
        ):
            raise ValueError(f"{_PATHS_MESSAGE} for scan_type {scan_type!r}")
        normalised["paths"] = list(paths)

    return normalised


SCAN_EVENTS_STREAM: Literal["scan.events"] = "scan.events"

# The database index that enforces the one-open-name-per-asset rule. The
# service never enforces that rule itself: the index is the authority and this
# name is only used to recognise its violation.
_OPEN_NAME_INDEX = "uq_scans_tenant_asset_name_pending"


class ScanDuplicateError(Exception):
    """Raised when a mutation violates the one-open-name-per-asset rule.

    Only one ``pending`` scan may exist per ``(tenant_id, asset_id, name)``,
    enforced by the database index ``uq_scans_tenant_asset_name_pending``. The
    router maps this to HTTP 409.
    """


def _add_tenant_predicate(stmt: Any, tenant_id: uuid.UUID | None) -> Any:
    """Apply the tenant predicate unless ``tenant_id`` is None.

    ``None`` is reserved for the deliberately global superadmin path. For any
    other caller it would silently widen the query, so the router must only
    pass None for a superadmin.
    """
    if tenant_id is not None:
        return stmt.where(Scan.tenant_id == tenant_id)
    return stmt


def _is_open_name_violation(exc: IntegrityError) -> bool:
    """Detect a uq_scans_tenant_asset_name_pending violation across drivers.

    Inspects the driver's constraint name first (asyncpg exposes it on the
    exception, psycopg on ``diag``) and falls back to the driver message.
    """
    orig = getattr(exc, "orig", None)
    if orig is None:
        return False

    name = getattr(orig, "constraint_name", None)
    if not name:
        diag = getattr(orig, "diag", None)
        name = getattr(diag, "constraint_name", None)
    if name and _OPEN_NAME_INDEX in str(name):
        return True

    return _OPEN_NAME_INDEX in str(orig)


async def create_scan(
    data: ScanCreateRequest,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Scan:
    """Create a new scan definition; persist then publish ``scan.created``.

    Ordering guarantee: config validation -> INSERT + flush (the partial
    unique index fires here) -> commit -> publish, so a failed commit
    publishes nothing and a Redis failure after commit cannot roll back the
    persisted row. Tenant-scoping rule: the row always carries the caller's
    ``tenant_id`` (creation is never global), and the lifecycle is forced
    server-side to ``pending`` with no operational timestamps, whatever the
    client sent.
    """
    normalised_config = _validate_scan_config(data.type, data.config.model_dump())

    scan = Scan(
        tenant_id=tenant_id,
        asset_id=data.asset_id,
        name=data.name,
        scan_type=data.type,
        status="pending",
        config=normalised_config,
        started_at=None,
        completed_at=None,
    )
    db.add(scan)
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_open_name_violation(exc):
            raise ScanDuplicateError(
                f"a pending scan named {data.name!r} already exists for this asset"
            ) from exc
        raise

    await db.commit()

    # Capture-after-flush / publish-after-commit: the snapshot is read from
    # the flushed row and only sent once commit succeeded.
    event = ScanCreatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        scan_id=scan.id,
        asset_id=scan.asset_id,
        name=scan.name,
        type=data.type,
        status=scan.status,
        config=scan.config,
        created_at=scan.created_at,
    )
    await event_bus.publish(event, stream=SCAN_EVENTS_STREAM)
    return scan


async def get_scan(
    scan_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> Scan | None:
    """Return the scan or None.

    Ordering guarantee: a single SELECT, no flush, no commit, no events.
    Tenant-scoping rule: when ``tenant_id`` is not None the predicate
    ``Scan.tenant_id == tenant_id`` is added explicitly (the database RLS
    policy is a second layer, not a substitute); ``None`` is the deliberately
    global superadmin path and adds no predicate.
    """
    stmt = _add_tenant_predicate(select(Scan).where(Scan.id == scan_id), tenant_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_scans(
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    asset_id: uuid.UUID | None = None,
) -> tuple[Sequence[Scan], int]:
    """Return ``(items, total)`` ordered by ``created_at DESC, id DESC``.

    Ordering guarantee: the count query runs first, then the items query with
    a deterministic ``created_at DESC, id DESC`` order plus offset/limit.
    Tenant-scoping rule: ``Scan.tenant_id == tenant_id`` is added to both
    queries when ``tenant_id`` is not None; ``None`` is the superadmin path.
    When ``asset_id`` is given, the SAME predicate is applied to both the
    count and the items query, so the page metadata can never disagree with
    the items it describes.
    """
    base_stmt = _add_tenant_predicate(select(Scan), tenant_id)
    count_stmt = _add_tenant_predicate(
        select(func.count()).select_from(Scan),
        tenant_id,
    )
    if asset_id is not None:
        base_stmt = base_stmt.where(Scan.asset_id == asset_id)
        count_stmt = count_stmt.where(Scan.asset_id == asset_id)

    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = (
        base_stmt.order_by(Scan.created_at.desc(), Scan.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_stmt)).scalars().all()
    return items, int(total or 0)


async def update_scan(
    scan_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    data: ScanUpdate,
    db: AsyncSession,
    event_bus: EventBus,
) -> Scan | None:
    """Apply a partial update; return the updated scan or None.

    Ordering guarantee: the EFFECTIVE ``(type, config)`` pair is validated on
    LOCAL values BEFORE any attribute of the ORM object is touched, so a
    rejected PATCH leaves both the database row AND the in-memory object
    (identity-map state) consistent; then flush (the partial unique index
    fires here), commit, and only after a successful commit is
    ``scan.updated`` published. Tenant-scoping rule: the row is fetched
    through the explicit ``Scan.tenant_id == tenant_id`` predicate unless
    ``tenant_id`` is None (superadmin path); an invisible scan yields
    ``None`` and publishes nothing.

    ``changed_fields`` lists only public fields whose value actually changed,
    in the fixed order ``name``, ``type``, ``config``.
    """
    stmt = _add_tenant_predicate(select(Scan).where(Scan.id == scan_id), tenant_id)
    scan = (await db.execute(stmt)).scalar_one_or_none()
    if scan is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    # Phase 1 - validate on locals. A rejection here raises before any
    # attribute is touched, so the in-memory object stays consistent with
    # the database row.
    candidate_name = update_data.get("name", scan.name)
    candidate_type = update_data.get("type", scan.scan_type)
    candidate_config = update_data.get("config", scan.config)
    normalised_config = _validate_scan_config(candidate_type, candidate_config)

    # Phase 2 - apply. Nothing can raise from here.
    changed_fields: list[str] = []
    if candidate_name != scan.name:
        scan.name = candidate_name
        changed_fields.append("name")
    if candidate_type != scan.scan_type:
        scan.scan_type = candidate_type
        changed_fields.append("type")
    if normalised_config != scan.config:
        scan.config = normalised_config
        changed_fields.append("config")

    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_open_name_violation(exc):
            raise ScanDuplicateError(
                "update would produce a second pending scan with the same "
                "name for this asset"
            ) from exc
        raise

    await db.commit()

    event = ScanUpdatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=scan.tenant_id,
        scan_id=scan.id,
        changed_fields=changed_fields,
    )
    await event_bus.publish(event, stream=SCAN_EVENTS_STREAM)
    return scan


async def delete_scan(
    scan_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    event_bus: EventBus,
) -> bool:
    """Delete the scan (tenant-scoped); return True on success, False on miss.

    Ordering guarantee: ``db.delete`` then ``commit``, and only after commit
    succeeds is ``scan.deleted`` published with the id and tenant captured
    BEFORE the delete, so a Redis failure cannot roll back the committed
    removal nor publish a corrupted snapshot. Tenant-scoping rule: the
    visibility SELECT carries the explicit ``Scan.tenant_id == tenant_id``
    predicate unless ``tenant_id`` is None (superadmin path); an invisible
    scan yields False and publishes nothing.
    """
    stmt = _add_tenant_predicate(select(Scan).where(Scan.id == scan_id), tenant_id)
    scan = (await db.execute(stmt)).scalar_one_or_none()
    if scan is None:
        return False

    captured_id = scan.id
    captured_tenant = scan.tenant_id

    await db.delete(scan)
    await db.commit()

    event = ScanDeletedEvent(
        event_id=uuid.uuid4(),
        tenant_id=captured_tenant,
        scan_id=captured_id,
    )
    await event_bus.publish(event, stream=SCAN_EVENTS_STREAM)
    return True
