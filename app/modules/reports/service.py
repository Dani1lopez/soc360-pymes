"""Report service: module-level async functions implementing the Reports CRUD.

Follows the same shape as ``app.modules.vulnerabilities.service``: standalone
``async def`` functions that take ``AsyncSession`` and ``EventBus`` explicitly,
with no class holding mutable state.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.event_bus import EventBus
from app.event_schemas import ReportCreatedEvent, ReportDeletedEvent, ReportUpdatedEvent
from app.modules.reports.models import Report
from app.modules.reports.schemas import (
    ReportCreate,
    ReportStatus,
    ReportType,
    ReportUpdate,
)

__all__ = [
    "REPORT_EVENTS_STREAM",
    "ReportAssetNotFoundError",
    "create_report",
    "delete_report",
    "get_report",
    "list_reports",
    "update_report",
]

REPORT_EVENTS_STREAM: Literal["report.events"] = "report.events"

# The composite FK guarding the report/asset relationship; its flush-time
# violation is the deleted-asset race.
_ASSET_FK_CONSTRAINT = "fk_reports_asset_tenant"

# Public PATCH fields, in the fixed order ``changed_fields`` reports them.
_UPDATABLE_FIELDS = ("name", "status", "summary", "report_metadata", "generated_at")


class ReportAssetNotFoundError(Exception):
    """Raised when the report's asset disappeared between resolution and INSERT.

    The router maps this to HTTP 404 with the same ``report asset not found``
    detail as the pre-INSERT path, so the two 404s are indistinguishable to
    the caller.
    """

    def __init__(self, message: str = "report asset not found") -> None:
        super().__init__(message)


def _add_tenant_predicate(stmt: Any, tenant_id: uuid.UUID | None) -> Any:
    """Apply the tenant predicate unless ``tenant_id`` is None.

    ``None`` is reserved for the deliberately global superadmin path. For any
    other caller it would silently widen the query, so the router must only
    pass None for a superadmin.
    """
    if tenant_id is not None:
        return stmt.where(Report.tenant_id == tenant_id)
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


def _is_asset_fk_violation(exc: IntegrityError) -> bool:
    """Detect an fk_reports_asset_tenant violation across drivers."""
    return _violates_constraint(exc, _ASSET_FK_CONSTRAINT)


async def create_report(
    data: ReportCreate,
    tenant_id: uuid.UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Report:
    """Create a new report; persist then publish ``report.created``.

    Ordering guarantee: INSERT + flush (the asset FK fires here) -> commit ->
    publish, so a failed commit publishes nothing and a Redis failure after
    commit cannot roll back the persisted row. Tenant-scoping rule: the row
    always carries the caller's ``tenant_id`` (creation is never global), and
    the lifecycle is forced server-side to ``"pending"`` with no
    ``generated_at``, whatever the client sent.
    """
    report = Report(
        tenant_id=tenant_id,
        asset_id=data.asset_id,
        name=data.name,
        report_type=data.report_type,
        status="pending",
        summary=data.summary,
        report_metadata=data.report_metadata,
        generated_at=None,
    )
    db.add(report)
    try:
        await db.flush()
    except IntegrityError as exc:
        if _is_asset_fk_violation(exc):
            raise ReportAssetNotFoundError("report asset not found") from exc
        raise

    await db.commit()

    # Capture-after-flush / publish-after-commit: the snapshot is read from
    # the flushed row and only sent once commit succeeded.
    event = ReportCreatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=tenant_id,
        report_id=report.id,
        asset_id=report.asset_id,
        name=report.name,
        report_type=report.report_type,
        status=report.status,
        created_at=report.created_at,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return report


async def get_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> Report | None:
    """Return the report or None.

    Ordering guarantee: a single SELECT, no flush, no commit, no events.
    Tenant-scoping rule: when ``tenant_id`` is not None the predicate
    ``Report.tenant_id == tenant_id`` is added explicitly (the database RLS
    policy is a second layer, not a substitute); ``None`` is the deliberately
    global superadmin path and adds no predicate.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_reports(
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    *,
    limit: int,
    offset: int,
    asset_id: uuid.UUID | None = None,
    report_type: ReportType | None = None,
    status: ReportStatus | None = None,
) -> tuple[Sequence[Report], int]:
    """Return ``(items, total)`` ordered by ``created_at DESC, id DESC``.

    Ordering guarantee: the count query runs first, then the items query with
    a deterministic ``created_at DESC, id DESC`` order plus offset/limit.
    Tenant-scoping rule: ``Report.tenant_id == tenant_id`` is added to both
    queries when ``tenant_id`` is not None; ``None`` is the superadmin path.
    Every optional filter is applied to BOTH the count and the items query,
    so the page metadata can never disagree with the items it describes.
    """
    filters = []
    if asset_id is not None:
        filters.append(Report.asset_id == asset_id)
    if report_type is not None:
        filters.append(Report.report_type == report_type)
    if status is not None:
        filters.append(Report.status == status)

    base_stmt = _add_tenant_predicate(select(Report), tenant_id).where(*filters)
    count_stmt = _add_tenant_predicate(
        select(func.count()).select_from(Report),
        tenant_id,
    ).where(*filters)

    total = (await db.execute(count_stmt)).scalar_one()

    items_stmt = (
        base_stmt.order_by(Report.created_at.desc(), Report.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = (await db.execute(items_stmt)).scalars().all()
    return items, int(total or 0)


async def update_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    data: ReportUpdate,
    db: AsyncSession,
    event_bus: EventBus,
) -> Report | None:
    """Apply a partial update; return the updated report or None.

    Ordering guarantee: flush, commit, and only after a successful commit is
    ``report.updated`` published. Tenant-scoping rule: the row is fetched
    through the explicit ``Report.tenant_id == tenant_id`` predicate unless
    ``tenant_id`` is None (superadmin path); an invisible report yields
    ``None`` and publishes nothing.

    ``changed_fields`` lists only public fields whose value actually changed,
    in the fixed order ``name``, ``status``, ``summary``, ``report_metadata``,
    ``generated_at``. When it is empty the flush and commit still run, but
    nothing is published.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        return None

    update_data = data.model_dump(exclude_unset=True)

    changed_fields: list[str] = []
    for field in _UPDATABLE_FIELDS:
        if field in update_data and update_data[field] != getattr(report, field):
            setattr(report, field, update_data[field])
            changed_fields.append(field)

    await db.flush()
    await db.commit()

    # Nothing public changed: no event.
    if not changed_fields:
        return report

    event = ReportUpdatedEvent(
        event_id=uuid.uuid4(),
        tenant_id=report.tenant_id,
        report_id=report.id,
        changed_fields=changed_fields,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return report


async def delete_report(
    report_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    event_bus: EventBus,
) -> bool:
    """Delete the report (tenant-scoped); return True on success, False on miss.

    Ordering guarantee: ``db.delete`` then ``commit``, and only after commit
    succeeds is ``report.deleted`` published with the id and tenant captured
    BEFORE the delete. Tenant-scoping rule: the visibility SELECT carries the
    explicit ``Report.tenant_id == tenant_id`` predicate unless ``tenant_id``
    is None (superadmin path); an invisible report yields False and
    publishes nothing.
    """
    stmt = _add_tenant_predicate(
        select(Report).where(Report.id == report_id), tenant_id
    )
    report = (await db.execute(stmt)).scalar_one_or_none()
    if report is None:
        return False

    captured_id = report.id
    captured_tenant = report.tenant_id

    await db.delete(report)
    await db.commit()

    event = ReportDeletedEvent(
        event_id=uuid.uuid4(),
        tenant_id=captured_tenant,
        report_id=captured_id,
    )
    await event_bus.publish(event, stream=REPORT_EVENTS_STREAM)
    return True
