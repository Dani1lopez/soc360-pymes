"""Asset router — Slice 1 vertical CRUD endpoints.

Routes registered under ``/api/v1/assets`` (see :mod:`app.main`).

RBAC matrix (design.md D-006) — exact allowlists only; ``superadmin`` is
never implicit:

* POST   — ``admin`` OR ``superadmin``
* GET    — ``admin`` OR ``analyst`` OR ``viewer`` OR ``superadmin``
* PATCH  — ``admin`` OR ``superadmin``
* DELETE — ``admin`` OR ``superadmin``

Tenant scoping (D-007): non-superadmin users see only their tenant's
assets; superadmin has no tenant predicate (RLS authorizes the cross-
tenant read with ``app.is_superadmin='true'``).
"""
from __future__ import annotations

import csv
import io
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import DBDep
from app.dependencies.auth import require_any_role
from app.dependencies.event_deps import get_event_bus
from app.event_bus import EventBus
from app.modules.assets import service
from app.modules.assets.models import Asset
from app.modules.assets.schemas import (
    AssetCreateRequest,
    AssetListResponse,
    AssetResponse,
    AssetUpdate,
)
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

router = APIRouter(prefix="/assets", tags=["assets"])


# Annotated-style dependency for EventBus — preferred FastAPI pattern.
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _scope_query(stmt: Any, current_user: User) -> Any:
    """Apply the tenant scope based on ``current_user.is_superadmin``.

    Non-superadmin users have ``Asset.tenant_id == current_user.tenant_id``
    added to the WHERE clause; superadmin users have NO tenant predicate
    (RLS authorizes cross-tenant reads under
    ``app.is_superadmin='true'``).
    """
    if not current_user.is_superadmin:
        if current_user.tenant_id is None:
            # Defensive: a non-superadmin without a tenant is impossible
            # per app.modules.users.models.chk_user_has_tenant. If the
            # invariant is broken, refuse to leak data.
            return stmt.where(False)
        return stmt.where(Asset.tenant_id == current_user.tenant_id)
    return stmt


_CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "type",
    "value",
    "tenant_id",
    "created_at",
    "updated_at",
)


def _row_to_csv_dict(asset: AssetResponse) -> dict[str, Any]:
    """Project a response into the CSV whitelist (same order as _CSV_COLUMNS)."""
    return {
        "id": str(asset.id),
        "type": asset.type,
        "value": asset.value,
        "tenant_id": str(asset.tenant_id),
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
    }


async def _stream_csv(
    db: AsyncSession,
    current_user: User,
) -> AsyncGenerator[bytes, None]:
    """Stream an unpaginated CSV over assets visible to ``current_user``.

    The query has no limit/offset so the export captures every visible
    row. Columns are exactly the six public fields. The yielded buffers
    are line-oriented so callers can stream them straight into a
    :class:`StreamingResponse`.
    """
    stmt = select(Asset).order_by(Asset.created_at.desc(), Asset.id.desc())
    stmt = _scope_query(stmt, current_user)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    yield buffer.getvalue().encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)

    result = await db.stream(stmt)
    async for asset in result:
        response = AssetResponse.from_orm_instance(asset)
        writer.writerow(_row_to_csv_dict(response))
        yield buffer.getvalue().encode("utf-8")
        buffer.seek(0)
        buffer.truncate(0)


# ---------------------------------------------------------------------------
# T8.2 — POST /assets
# ---------------------------------------------------------------------------
@router.post(
    "/",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new asset",
)
async def create_asset(
    payload: AssetCreateRequest,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> AssetResponse:
    """Create a new asset within a tenant.

    Tenant rules (D-007):

    * Non-superadmin: ``payload.tenant_id`` MUST equal
      ``current_user.tenant_id``; otherwise 422 ``tenant_id mismatch``.
    * Superadmin: ``payload.tenant_id`` MUST be present and must resolve
      to an existing tenant; otherwise 422.
    """
    if current_user.is_superadmin:
        if payload.tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tenant_id is required",
            )
        tenant = (
            await db.execute(select(Tenant).where(Tenant.id == payload.tenant_id))
        ).scalar_one_or_none()
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tenant not found",
            )
        effective_tenant_id = payload.tenant_id
    else:
        if payload.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tenant_id mismatch",
            )
        effective_tenant_id = payload.tenant_id

    try:
        asset = await service.create_asset(
            data=payload,
            tenant_id=effective_tenant_id,
            db=db,
            event_bus=event_bus,
        )
    except service.AssetDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    except ValueError as exc:
        # Contract messages from _validate_asset_value; router maps verbatim.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return AssetResponse.from_orm_instance(asset)


# ---------------------------------------------------------------------------
# T8.3 — GET /assets (list or CSV)
# ---------------------------------------------------------------------------
@router.get(
    "/",
    response_model=None,
    summary="List assets (paginated) or export them as CSV",
)
async def list_assets(
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    export: Literal["csv"] | None = None,
) -> Any:
    """List assets visible to ``current_user``.

    With ``export=csv`` an unpaginated ``text/csv`` stream is returned;
    otherwise a paginated :class:`AssetListResponse` is returned.
    """
    if export == "csv":
        return StreamingResponse(
            _stream_csv(db, current_user),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=assets.csv",
            },
        )

    tenant_id: uuid.UUID | None
    if current_user.is_superadmin:
        tenant_id = None
    else:
        tenant_id = current_user.tenant_id

    items, total = await service.list_assets(
        tenant_id=tenant_id, db=db, limit=limit, offset=offset
    )
    return AssetListResponse(
        items=[AssetResponse.from_orm_instance(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# T8.4 — GET /assets/{id}
# ---------------------------------------------------------------------------
@router.get(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Get an asset by id",
)
async def get_asset(
    asset_id: uuid.UUID,
    db: DBDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
) -> AssetResponse:
    """Return the asset, or 404 if it doesn't exist in the visible scope."""
    stmt = select(Asset).where(Asset.id == asset_id)
    stmt = _scope_query(stmt, current_user)
    asset = (await db.execute(stmt)).scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="asset not found"
        )
    return AssetResponse.from_orm_instance(asset)


# ---------------------------------------------------------------------------
# T8.5 — PATCH /assets/{id}
# ---------------------------------------------------------------------------
@router.patch(
    "/{asset_id}",
    response_model=AssetResponse,
    summary="Update an asset",
)
async def update_asset(
    asset_id: uuid.UUID,
    payload: AssetUpdate,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> AssetResponse:
    """Apply a partial update to an asset."""
    tenant_id: uuid.UUID | None = (
        None if current_user.is_superadmin else current_user.tenant_id
    )
    try:
        asset = await service.update_asset(
            asset_id=asset_id,
            tenant_id=tenant_id,
            data=payload,
            db=db,
            event_bus=event_bus,
        )
    except service.AssetDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="asset not found"
        )
    return AssetResponse.from_orm_instance(asset)


# ---------------------------------------------------------------------------
# T8.6 — DELETE /assets/{id}
# ---------------------------------------------------------------------------
@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Delete an asset",
)
async def delete_asset(
    asset_id: uuid.UUID,
    db: DBDep,
    event_bus: EventBusDep,
    current_user: User = Depends(require_any_role("admin", "superadmin")),
) -> None:
    """Delete an asset. 404 if it doesn't exist in the visible scope."""
    tenant_id: uuid.UUID | None = (
        None if current_user.is_superadmin else current_user.tenant_id
    )
    deleted = await service.delete_asset(
        asset_id=asset_id,
        tenant_id=tenant_id,
        db=db,
        event_bus=event_bus,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="asset not found"
        )
