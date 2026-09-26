"""Report router — Slice 4 (F2) CRUD endpoints.

Routes registered under ``/api/v1/reports`` (see :mod:`app.main`).

RBAC matrix — exact allowlists only; ``superadmin`` is never implicit:

* POST   — ``admin`` OR ``superadmin``
* GET (list + by-id) — ``admin`` OR ``analyst`` OR ``viewer`` OR ``superadmin``
* PATCH  — ``admin`` OR ``superadmin``
* DELETE — ``admin`` OR ``superadmin``

``ingestor`` is in NO allowlist: every reports operation answers 403 from the
dependency itself, before any existence or tenant check.

Tenant rules:

* POST requires ``tenant_id`` in the body (required field on
  :class:`ReportCreate`). A non-superadmin must send their own tenant,
  otherwise 422 ``tenant_id mismatch``; for a superadmin it is the explicit
  target tenant.
* Before creating, the asset is resolved as visible AND belonging to the
  effective target tenant (``Asset.id == asset_id`` AND
  ``Asset.tenant_id == target_tenant_id``). A miss is 404
  ``report asset not found`` and no report is persisted.
* ``GET /reports?asset_id=...`` runs the SAME asset resolution first, so an
  invisible or missing asset is 404 rather than an empty page.
* Cross-tenant by-id access returns 404, never 403, so existence is not
  leaked.
* ``tenant_id=None`` is reserved for the deliberately global superadmin
  path; everyone else's service call carries ``current_user.tenant_id``.

Generation is out of scope for this slice: ``status`` and ``generated_at``
are only ever changed by an explicit PATCH.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.dependencies import DBDep
from app.dependencies.auth import require_any_role
from app.dependencies.event_deps import get_event_bus
from app.event_bus import EventBus
from app.modules.assets.models import Asset
from app.modules.reports import service
from app.modules.reports.schemas import (
    ReportCreate,
    ReportListResponse,
    ReportResponse,
    ReportStatus,
    ReportType,
    ReportUpdate,
)
from app.modules.users.models import User

router = APIRouter(prefix="/reports", tags=["reports"])


# Annotated-style dependency for EventBus — preferred FastAPI pattern.
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _effective_tenant_id(payload_tenant_id: uuid.UUID, current_user: User) -> uuid.UUID:
    """Return the tenant the report must belong to.

    Non-superadmin: ``payload.tenant_id`` MUST equal
    ``current_user.tenant_id``; otherwise 422 ``tenant_id mismatch``.
    Superadmin: ``payload.tenant_id`` is the explicit target tenant.
    """
    if not current_user.is_superadmin and payload_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_id mismatch",
        )
    return payload_tenant_id


async def _resolve_report_asset(
    db: Any,
    asset_id: uuid.UUID,
    target_tenant_id: uuid.UUID | None,
) -> None:
    """404 ``report asset not found`` unless the asset resolves in scope.

    ``target_tenant_id=None`` is the superadmin path — the RLS context
    authorizes the cross-tenant read, so only existence is checked.
    """
    stmt = select(Asset).where(Asset.id == asset_id)
    if target_tenant_id is not None:
        stmt = stmt.where(Asset.tenant_id == target_tenant_id)
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report asset not found"
        )


def _caller_tenant_id(current_user: User) -> uuid.UUID | None:
    """Tenant predicate for the service: ``None`` only for a superadmin."""
    return None if current_user.is_superadmin else current_user.tenant_id


# ---------------------------------------------------------------------------
# POST /reports
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new report",
)
async def create_report(
    payload: ReportCreate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> ReportResponse:
    """Create a new report for a visible asset of the effective target tenant.

    The asset must resolve as ``Asset.id == asset_id`` AND
    ``Asset.tenant_id == effective tenant`` (even for a superadmin — this
    validates the report/asset coherence, not global visibility). A miss is
    404 ``report asset not found`` and nothing is persisted.
    """
    effective_tenant_id = _effective_tenant_id(payload.tenant_id, current_user)
    await _resolve_report_asset(db, payload.asset_id, effective_tenant_id)

    try:
        report = await service.create_report(
            data=payload,
            tenant_id=effective_tenant_id,
            db=db,
            event_bus=event_bus,
        )
    except service.ReportAssetNotFoundError as exc:
        # Deleted-asset race: flush-time FK violation -> same 404 detail as
        # the pre-INSERT _resolve_report_asset path.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return ReportResponse.from_orm_instance(report)


# ---------------------------------------------------------------------------
# GET /reports (list)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=ReportListResponse,
    summary="List reports (paginated), optionally filtered",
)
async def list_reports(
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    asset_id: uuid.UUID | None = Query(None),
    report_type: ReportType | None = Query(None),
    report_status: ReportStatus | None = Query(None, alias="status"),
) -> ReportListResponse:
    """List reports visible to ``current_user``, newest first.

    With ``asset_id`` the SAME asset resolution as POST runs first, so an
    invisible or missing asset is 404 rather than an empty page.
    """
    if asset_id is not None:
        await _resolve_report_asset(db, asset_id, _caller_tenant_id(current_user))

    items, total = await service.list_reports(
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        limit=limit,
        offset=offset,
        asset_id=asset_id,
        report_type=report_type,
        status=report_status,
    )
    return ReportListResponse(
        items=[ReportResponse.from_orm_instance(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /reports/{report_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Get a report by id",
)
async def get_report(
    report_id: uuid.UUID,
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
) -> ReportResponse:
    """Return the report, or 404 if it doesn't exist in the visible scope."""
    report = await service.get_report(
        report_id=report_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
        )
    return ReportResponse.from_orm_instance(report)


# ---------------------------------------------------------------------------
# PATCH /reports/{report_id}
# ---------------------------------------------------------------------------
@router.patch(
    "/{report_id}",
    response_model=ReportResponse,
    summary="Update a report",
)
async def update_report(
    report_id: uuid.UUID,
    payload: ReportUpdate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> ReportResponse:
    """Apply a partial update to a report."""
    report = await service.update_report(
        report_id=report_id,
        tenant_id=_caller_tenant_id(current_user),
        data=payload,
        db=db,
        event_bus=event_bus,
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
        )
    return ReportResponse.from_orm_instance(report)


# ---------------------------------------------------------------------------
# DELETE /reports/{report_id}
# ---------------------------------------------------------------------------
@router.delete(
    "/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a report",
)
async def delete_report(
    report_id: uuid.UUID,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> None:
    """Delete a report. 404 if it doesn't exist in the visible scope."""
    deleted = await service.delete_report(
        report_id=report_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        event_bus=event_bus,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="report not found"
        )
