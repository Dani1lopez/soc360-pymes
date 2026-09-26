"""Vulnerability router — Slice 3 (F2) CRUD endpoints.

Routes registered under ``/api/v1/vulnerabilities`` (see :mod:`app.main`).

RBAC matrix — exact allowlists only; ``superadmin`` is never implicit:

* POST   — ``admin`` OR ``superadmin``
* GET (list + by-id) — ``admin`` OR ``analyst`` OR ``viewer`` OR ``superadmin``
* PATCH  — ``admin`` OR ``superadmin``
* DELETE — ``admin`` OR ``superadmin``

``ingestor`` is in NO allowlist: every vulnerabilities operation answers 403
from the dependency itself, before any existence or tenant check.

Tenant rules:

* POST requires ``tenant_id`` in the body (required field on
  :class:`VulnerabilityCreate`). A non-superadmin must send their own
  tenant, otherwise 422 ``tenant_id mismatch``; for a superadmin it is the
  explicit target tenant.
* Before creating, the scan is resolved as visible AND belonging to the
  effective target tenant (``Scan.id == scan_id`` AND
  ``Scan.tenant_id == target_tenant_id``). A miss is 404
  ``vulnerability scan not found`` and no vulnerability is persisted.
* ``GET /vulnerabilities?scan_id=...`` runs the SAME scan resolution first,
  so an invisible or missing scan is 404 rather than an empty page.
* Cross-tenant by-id access returns 404, never 403, so existence is not
  leaked.
* ``tenant_id=None`` is reserved for the deliberately global superadmin
  path; everyone else's service call carries ``current_user.tenant_id``.
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
from app.modules.scans.models import Scan
from app.modules.users.models import User
from app.modules.vulnerabilities import service
from app.modules.vulnerabilities.schemas import (
    VulnerabilityCreate,
    VulnerabilityListResponse,
    VulnerabilityResponse,
    VulnerabilityUpdate,
)

router = APIRouter(prefix="/vulnerabilities", tags=["vulnerabilities"])


# Annotated-style dependency for EventBus — preferred FastAPI pattern.
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _effective_tenant_id(payload_tenant_id: uuid.UUID, current_user: User) -> uuid.UUID:
    """Return the tenant the vulnerability must belong to.

    Non-superadmin: ``payload.tenant_id`` MUST equal
    ``current_user.tenant_id``; otherwise 422 ``tenant_id mismatch``.
    Superadmin: ``payload.tenant_id`` is the explicit target tenant (the
    create schema requires it, so it cannot be ``None`` here).
    """
    if not current_user.is_superadmin and payload_tenant_id != current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_id mismatch",
        )
    return payload_tenant_id


async def _resolve_vulnerability_scan(
    db: Any,
    scan_id: uuid.UUID,
    target_tenant_id: uuid.UUID | None,
) -> None:
    """404 ``vulnerability scan not found`` unless the scan resolves in scope.

    The vulnerability/scan relationship must be coherent: the scan must
    belong to the effective target tenant (and, for a non-superadmin, be
    visible in their tenant). ``target_tenant_id=None`` is the superadmin
    path — the RLS context authorizes the cross-tenant read, so only
    existence is checked.
    """
    stmt = select(Scan).where(Scan.id == scan_id)
    if target_tenant_id is not None:
        stmt = stmt.where(Scan.tenant_id == target_tenant_id)
    scan = (await db.execute(stmt)).scalar_one_or_none()
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="vulnerability scan not found"
        )


def _caller_tenant_id(current_user: User) -> uuid.UUID | None:
    """Tenant predicate for the service: ``None`` only for a superadmin."""
    return None if current_user.is_superadmin else current_user.tenant_id


# ---------------------------------------------------------------------------
# POST /vulnerabilities
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=VulnerabilityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new vulnerability",
)
async def create_vulnerability(
    payload: VulnerabilityCreate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> VulnerabilityResponse:
    """Create a new vulnerability for a visible scan of the effective target tenant.

    The scan must resolve as ``Scan.id == scan_id`` AND
    ``Scan.tenant_id == effective tenant`` (even for a superadmin — this
    validates the vulnerability/scan coherence, not global visibility). A
    miss is 404 ``vulnerability scan not found`` and nothing is persisted.
    """
    effective_tenant_id = _effective_tenant_id(payload.tenant_id, current_user)
    await _resolve_vulnerability_scan(db, payload.scan_id, effective_tenant_id)

    try:
        vulnerability = await service.create_vulnerability(
            data=payload,
            tenant_id=effective_tenant_id,
            db=db,
            event_bus=event_bus,
        )
    except service.VulnerabilityScanNotFoundError as exc:
        # Deleted-scan race: flush-time FK violation -> same 404 detail as
        # the pre-INSERT _resolve_vulnerability_scan path.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return VulnerabilityResponse.from_orm_instance(vulnerability)


# ---------------------------------------------------------------------------
# GET /vulnerabilities (list)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=VulnerabilityListResponse,
    summary="List vulnerabilities (paginated), optionally filtered by scan",
)
async def list_vulnerabilities(
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    scan_id: uuid.UUID | None = Query(None),
) -> VulnerabilityListResponse:
    """List vulnerabilities visible to ``current_user``, newest first.

    With ``scan_id`` the SAME scan resolution as POST runs first, so an
    invisible or missing scan is 404 rather than an empty page.
    """
    if scan_id is not None:
        await _resolve_vulnerability_scan(db, scan_id, _caller_tenant_id(current_user))

    items, total = await service.list_vulnerabilities(
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        limit=limit,
        offset=offset,
        scan_id=scan_id,
    )
    return VulnerabilityListResponse(
        items=[VulnerabilityResponse.from_orm_instance(v) for v in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /vulnerabilities/{vulnerability_id}
# ---------------------------------------------------------------------------
@router.get(
    "/{vulnerability_id}",
    response_model=VulnerabilityResponse,
    summary="Get a vulnerability by id",
)
async def get_vulnerability(
    vulnerability_id: uuid.UUID,
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
) -> VulnerabilityResponse:
    """Return the vulnerability, or 404 if it doesn't exist in the visible scope."""
    vulnerability = await service.get_vulnerability(
        vulnerability_id=vulnerability_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
    )
    if vulnerability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="vulnerability not found"
        )
    return VulnerabilityResponse.from_orm_instance(vulnerability)


# ---------------------------------------------------------------------------
# PATCH /vulnerabilities/{vulnerability_id}
# ---------------------------------------------------------------------------
@router.patch(
    "/{vulnerability_id}",
    response_model=VulnerabilityResponse,
    summary="Update a vulnerability",
)
async def update_vulnerability(
    vulnerability_id: uuid.UUID,
    payload: VulnerabilityUpdate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> VulnerabilityResponse:
    """Apply a partial update to a vulnerability."""
    vulnerability = await service.update_vulnerability(
        vulnerability_id=vulnerability_id,
        tenant_id=_caller_tenant_id(current_user),
        data=payload,
        db=db,
        event_bus=event_bus,
    )
    if vulnerability is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="vulnerability not found"
        )
    return VulnerabilityResponse.from_orm_instance(vulnerability)


# ---------------------------------------------------------------------------
# DELETE /vulnerabilities/{vulnerability_id}
# ---------------------------------------------------------------------------
@router.delete(
    "/{vulnerability_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete a vulnerability",
)
async def delete_vulnerability(
    vulnerability_id: uuid.UUID,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> None:
    """Delete a vulnerability. 404 if it doesn't exist in the visible scope."""
    deleted = await service.delete_vulnerability(
        vulnerability_id=vulnerability_id,
        tenant_id=_caller_tenant_id(current_user),
        db=db,
        event_bus=event_bus,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="vulnerability not found"
        )
