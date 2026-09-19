"""Scan router — Slice 2 (F2) CRUD endpoints.

Routes registered under ``/api/v1/scans`` (see :mod:`app.main`).

RBAC matrix — exact allowlists only; ``superadmin`` is never implicit:

* POST   — ``admin`` OR ``superadmin``
* GET (list + by-id) — ``admin`` OR ``analyst`` OR ``viewer`` OR ``superadmin``
* PATCH  — ``admin`` OR ``superadmin``
* DELETE — ``admin`` OR ``superadmin``

``ingestor`` is in NO allowlist: every scans operation answers 403 from the
dependency itself, before any existence or tenant check.

Tenant rules:

* POST requires ``tenant_id`` in the body (required field on the create
  schemas). A non-superadmin must send their own tenant, otherwise 422
  ``tenant_id mismatch``; for a superadmin it is the explicit target tenant.
* Before creating, the asset is resolved as visible AND belonging to the
  effective target tenant (``Asset.id == asset_id`` AND
  ``Asset.tenant_id == target_tenant_id``). A miss is 404
  ``scan asset not found`` and no scan is persisted.
* ``GET /scans?asset_id=...`` runs the SAME asset resolution first, so an
  invisible or missing asset is 404 rather than an empty page.
* Cross-tenant by-id access returns 404, never 403, so existence is not leaked.
* ``tenant_id=None`` is reserved for the deliberately global superadmin path;
  everyone else's service call carries ``current_user.tenant_id``.
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
from app.modules.scans import service
from app.modules.scans.schemas import (
    ScanCreateRequest,
    ScanListResponse,
    ScanResponse,
    ScanUpdate,
)
from app.modules.users.models import User

router = APIRouter(prefix="/scans", tags=["scans"])


# Annotated-style dependency for EventBus — preferred FastAPI pattern.
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _effective_tenant_id(payload_tenant_id: uuid.UUID, current_user: User) -> uuid.UUID:
    """Return the tenant the scan must belong to.

    Non-superadmin: ``payload.tenant_id`` MUST equal
    ``current_user.tenant_id``; otherwise 422 ``tenant_id mismatch``.
    Superadmin: ``payload.tenant_id`` is the explicit target tenant (the
    create schemas require it, so it cannot be ``None`` here).
    """
    if not current_user.is_superadmin and payload_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_id mismatch",
        )
    return payload_tenant_id


async def _resolve_scan_asset(
    db: Any,
    asset_id: uuid.UUID,
    target_tenant_id: uuid.UUID | None,
) -> None:
    """404 ``scan asset not found`` unless the asset resolves in scope.

    The scan/asset relationship must be coherent: the asset must belong to
    the effective target tenant (and, for a non-superadmin, be visible in
    their tenant). ``target_tenant_id=None`` is the superadmin path — the
    RLS context authorizes the cross-tenant read, so only existence is
    checked.
    """
    stmt = select(Asset).where(Asset.id == asset_id)
    if target_tenant_id is not None:
        stmt = stmt.where(Asset.tenant_id == target_tenant_id)
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="scan asset not found"
        )


def _caller_tenant_id(current_user: User) -> uuid.UUID | None:
    """Tenant predicate for the service: ``None`` only for a superadmin."""
    return None if current_user.is_superadmin else current_user.tenant_id


# ---------------------------------------------------------------------------
# POST /scans
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=ScanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new scan definition",
)
async def create_scan(
    payload: ScanCreateRequest,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> ScanResponse:
    """Create a new scan for a visible asset of the effective target tenant.

    The asset must resolve as ``Asset.id == asset_id`` AND
    ``Asset.tenant_id == effective tenant`` (even for a superadmin — this
    validates the scan/asset coherence, not global visibility). A miss is
    404 ``scan asset not found`` and nothing is persisted.
    """
    effective_tenant_id = _effective_tenant_id(payload.tenant_id, current_user)
    await _resolve_scan_asset(
        db, payload.asset_id, effective_tenant_id
    )

    try:
        scan = await service.create_scan(
            data=payload,
            tenant_id=effective_tenant_id,
            db=db,
            event_bus=event_bus,
        )
    except service.ScanDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        # Contract messages from _validate_scan_config; router maps verbatim.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return ScanResponse.from_orm_instance(scan)


# ---------------------------------------------------------------------------
# GET /scans (list)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=ScanListResponse,
    summary="List scans (paginated), optionally filtered by asset",
)
async def list_scans(
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    asset_id: uuid.UUID | None = Query(None),
) -> ScanListResponse:
    """List scans visible to ``current_user``, newest first.

    With ``asset_id`` the SAME asset resolution as POST runs first, so an
    invisible or missing asset is 404 rather than an empty page.
    """
    if asset_id is not None:
        await _resolve_scan_asset(db, asset_id, _caller_tenant_id(current_user))

    items, total = await service.list_scans(
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        limit=limit,
        offset=offset,
        asset_id=asset_id,
    )
    return ScanListResponse(
        items=[ScanResponse.from_orm_instance(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /scans/{scan_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{scan_id}",
    response_model=ScanResponse,
    summary="Get a scan by id",
)
async def get_scan(
    scan_id: uuid.UUID,
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
) -> ScanResponse:
    """Return the scan, or 404 if it doesn't exist in the visible scope."""
    scan = await service.get_scan(
        scan_id=scan_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
    )
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="scan not found"
        )
    return ScanResponse.from_orm_instance(scan)


# ---------------------------------------------------------------------------
# PATCH /scans/{scan_id}
# ---------------------------------------------------------------------------
@router.patch(
    "/{scan_id}",
    response_model=ScanResponse,
    summary="Update a scan",
)
async def update_scan(
    scan_id: uuid.UUID,
    payload: ScanUpdate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> ScanResponse:
    """Apply a partial update to a scan."""
    try:
        scan = await service.update_scan(
            scan_id=scan_id,
            tenant_id=_caller_tenant_id(current_user),
            data=payload,
            db=db,
            event_bus=event_bus,
        )
    except service.ScanDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="scan not found"
        )
    return ScanResponse.from_orm_instance(scan)


# ---------------------------------------------------------------------------
# DELETE /scans/{scan_id}
# ---------------------------------------------------------------------------
@router.delete(
    "/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a scan",
)
async def delete_scan(
    scan_id: uuid.UUID,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> None:
    """Delete a scan. 404 if it doesn't exist in the visible scope."""
    deleted = await service.delete_scan(
        scan_id=scan_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        event_bus=event_bus,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="scan not found"
        )
