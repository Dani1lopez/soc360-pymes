"""Vulnerability service: module-level async functions implementing the
Vulnerabilities CRUD.

Follows the same shape as ``app.modules.scans.service``: standalone
``async def`` functions that take ``AsyncSession`` and ``EventBus`` explicitly,
with no class holding mutable state.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.event_bus import EventBus
from app.event_schemas import (
    VulnerabilityCreatedEvent,
    VulnerabilityDeletedEvent,
    VulnerabilityUpdatedEvent,
)
from app.modules.vulnerabilities.models import Vulnerability
from app.modules.vulnerabilities.schemas import VulnerabilityCreate, VulnerabilityUpdate

__all__ = [
    "VULNERABILITY_EVENTS_STREAM",
    "VulnerabilityScanNotFoundError",
    "create_vulnerability",
    "delete_vulnerability",
    "get_vulnerability",
    "list_vulnerabilities",
    "update_vulnerability",
]

VULNERABILITY_EVENTS_STREAM: Literal["vulnerability.events"] = "vulnerability.events"

# The composite FK guarding the vulnerability/scan relationship; its
# flush-time violation is the deleted-scan race.
_SCAN_FK_CONSTRAINT = "fk_vulnerabilities_scan_tenant"


class VulnerabilityScanNotFoundError(Exception):
    """Raised when the vulnerability's scan disappeared between resolution and INSERT.

    The deleted-scan race: the router validated the scan moments before the
    INSERT, but ``fk_vulnerabilities_scan_tenant`` fires at flush time. The
    router maps this to HTTP 404 with the same ``vulnerability scan not
    found`` detail as the pre-INSERT path, so the two 404s are
    indistinguishable to the caller.
    """

    def __init__(self, message: str = "vulnerability scan not found") -> None:
        super().__init__(message)


def _add_tenant_predicate(stmt: Any, tenant_id: uuid.UUID | None) -> Any:
    """Apply the tenant predicate unless ``tenant_id`` is None.

    ``None`` is reserved for the deliberately global superadmin path. For any
    other caller it would silently widen the query, so the router must only
    pass None for a superadmin.
    """
    if tenant_id is not None:
        return stmt.where(Vulnerability.tenant_id == tenant_id)
    return stmt


def _violates_constraint(exc: IntegrityError, constraint_name: str) -> bool:
    """Detect a named-constraint violation across drivers.

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
    if name and constraint_name in str(name):
        return True

    return constraint_name in str(orig)


def _is_scan_fk_violation(exc: IntegrityError) -> bool:
    """Detect an fk_vulnerabilities_scan_tenant violation across drivers."""
    return _violates_constraint(exc, _SCAN_FK_CONSTRAINT)


async def create_vulnerability(
    data: VulnerabilityCreate,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Vulnerability:
    """Create a new vulnerability; persist then publish ``vulnerability.created``.

    Ordering guarantee: INSERT + flush (the scan FK fires here) -> commit ->
    publish, so a failed commit publishes nothing and a Redis failure after
    commit cannot roll back the persisted row. Tenant-scoping rule: the row
    always carries the caller's ``tenant_id`` (creation is never global), and
    the lifecycle is forced server-side to ``"open"``, whatever the client
    sent.
    """
    vulnerability = Vulnerability(
        tenant_id=tenant_id,
        scan_id=data.scan_id,
        title=data.title,
        description=data.description,
        severity=data.severity,
        status="open",
        cve_id=data.cve_id,
        cvss_score=data.cvss_score,
        vulnerability_metadata=data.vulnerability_metadata,
    )
    db.add(vulnerability)
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_scan_fk_violation(exc):
            raise VulnerabilityScanNotFoundError("vulnerability scan not found") from exc
        raise

    await db.commit()

    # Capture-after-flush / publish-after-commit: the snapshot is read from
    # the flushed row and only sent once commit succeeded.
    event = VulnerabilityCreatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        vulnerability_id=vulnerability.id,
        scan_id=vulnerability.scan_id,
        title=vulnerability.title,
        severity=vulnerability.severity,
        status=vulnerability.status,
        cve_id=vulnerability.cve_id,
        cvss_score=(
            float(vulnerability.cvss_score)
            if vulnerability.cvss_score is not None
            else None
        ),
        created_at=vulnerability.created_at,
    )
    await event_bus.publish(event, stream=VULNERABILITY_EVENTS_STREAM)
    return vulnerability


async def get_vulnerability(
    vulnerability_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> Vulnerability | None:
    """Return the vulnerability or None.

    Ordering guarantee: a single SELECT, no flush, no commit, no events.
    Tenant-scoping rule: when ``tenant_id`` is not None the predicate
    ``Vulnerability.tenant_id == tenant_id`` is added explicitly (the
    database RLS policy is a second layer, not a substitute); ``None`` is the
    deliberately global superadmin path and adds no predicate.
    """
    stmt = _add_tenant_predicate(
        select(Vulnerability).where(Vulnerability.id == vulnerability_id), tenant_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_vulnerabilities(
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    scan_id: uuid.UUID | None = None,
) -> tuple[Sequence[Vulnerability], int]:
    """Return ``(items, total)`` ordered by ``created_at DESC, id DESC``.

    Ordering guarantee: the count query runs first, then the items query with
    a deterministic ``created_at DESC, id DESC`` order plus offset/limit.
    Tenant-scoping rule: ``Vulnerability.tenant_id == tenant_id`` is added to
    both queries when ``tenant_id`` is not None; ``None`` is the superadmin
    path. When ``scan_id`` is given, the SAME predicate is applied to both
    the count and the items query, so the page metadata can never disagree
    with the items it describes.
    """
    base_stmt = _add_tenant_predicate(select(Vulnerability), tenant_id)
    count_stmt = _add_tenant_predicate(
        select(func.count()).select_from(Vulnerability),
        tenant_id,
    )
    if scan_id is not None:
        base_stmt = base_stmt.where(Vulnerability.scan_id == scan_id)
        count_stmt = count_stmt.where(Vulnerability.scan_id == scan_id)

    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = (
        base_stmt.order_by(Vulnerability.created_at.desc(), Vulnerability.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_stmt)).scalars().all()
    return items, int(total or 0)


async def update_vulnerability(
    vulnerability_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    data: VulnerabilityUpdate,
    db: AsyncSession,
    event_bus: EventBus,
) -> Vulnerability | None:
    """Apply a partial update; return the updated vulnerability or None.

    Ordering guarantee: flush, commit, and only after a successful commit is
    ``vulnerability.updated`` published. Tenant-scoping rule: the row is
    fetched through the explicit ``Vulnerability.tenant_id == tenant_id``
    predicate unless ``tenant_id`` is None (superadmin path); an invisible
    vulnerability yields ``None`` and publishes nothing.

    ``changed_fields`` lists only public fields whose value actually changed,
    in the fixed order ``status``, ``description``, ``cvss_score``,
    ``vulnerability_metadata``. When it is empty - every sent value already
    matches the row - the flush and commit still run, but nothing is
    published: a PATCH that changed nothing is not an update, so no
    ``vulnerability.updated`` event is emitted.
    """
    stmt = _add_tenant_predicate(
        select(Vulnerability).where(Vulnerability.id == vulnerability_id), tenant_id
    )
    vulnerability = (await db.execute(stmt)).scalar_one_or_none()
    if vulnerability is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    changed_fields: list[str] = []
    if "status" in update_data and update_data["status"] != vulnerability.status:
        vulnerability.status = update_data["status"]
        changed_fields.append("status")
    if (
        "description" in update_data
        and update_data["description"] != vulnerability.description
    ):
        vulnerability.description = update_data["description"]
        changed_fields.append("description")
    if "cvss_score" in update_data:
        score = update_data["cvss_score"]
        normalized_score = (
            Decimal(str(score)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            if score is not None
            else None
        )
        if normalized_score != vulnerability.cvss_score:
            vulnerability.cvss_score = normalized_score
            changed_fields.append("cvss_score")
    if (
        "vulnerability_metadata" in update_data
        and update_data["vulnerability_metadata"] != vulnerability.vulnerability_metadata
    ):
        vulnerability.vulnerability_metadata = update_data["vulnerability_metadata"]
        changed_fields.append("vulnerability_metadata")

    await db.flush()
    await db.commit()

    # Nothing public changed: no event. The flush and commit still ran, but a
    # PATCH whose values already match the row is not an update, so
    # publishing an empty ``vulnerability.updated`` would be noise for
    # consumers.
    if not changed_fields:
        return vulnerability

    event = VulnerabilityUpdatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=vulnerability.tenant_id,
        vulnerability_id=vulnerability.id,
        changed_fields=changed_fields,
    )
    await event_bus.publish(event, stream=VULNERABILITY_EVENTS_STREAM)
    return vulnerability


async def delete_vulnerability(
    vulnerability_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    event_bus: EventBus,
) -> bool:
    """Delete the vulnerability (tenant-scoped); return True on success, False on miss.

    Ordering guarantee: ``db.delete`` then ``commit``, and only after commit
    succeeds is ``vulnerability.deleted`` published with the id and tenant
    captured BEFORE the delete, so a Redis failure cannot roll back the
    committed removal nor publish a corrupted snapshot. Tenant-scoping rule:
    the visibility SELECT carries the explicit
    ``Vulnerability.tenant_id == tenant_id`` predicate unless ``tenant_id``
    is None (superadmin path); an invisible vulnerability yields False and
    publishes nothing.
    """
    stmt = _add_tenant_predicate(
        select(Vulnerability).where(Vulnerability.id == vulnerability_id), tenant_id
    )
    vulnerability = (await db.execute(stmt)).scalar_one_or_none()
    if vulnerability is None:
        return False

    captured_id = vulnerability.id
    captured_tenant = vulnerability.tenant_id

    await db.delete(vulnerability)
    await db.commit()

    event = VulnerabilityDeletedEvent(
        event_id=uuid.uuid4(),
        tenant_id=captured_tenant,
        vulnerability_id=captured_id,
    )
    await event_bus.publish(event, stream=VULNERABILITY_EVENTS_STREAM)
    return True
