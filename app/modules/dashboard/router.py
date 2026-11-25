"""Tenant-scoped dashboard endpoint with a best-effort summary cache."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.dependencies import DBWithTenantDep, RedisDep
from app.dependencies.auth import require_any_role
from app.modules.dashboard import service
from app.modules.dashboard.schemas import DashboardSummary
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
logger = get_logger(__name__)
SUMMARY_CACHE_TTL_SECONDS = 60


async def _cached_summary(
    db: AsyncSession, redis: Redis, tenant_id: uuid.UUID
) -> DashboardSummary:
    """Read cached metrics or aggregate and cache them without requiring Redis."""
    # All allowed roles share a cache because the payload is tenant-level.
    key = f"dashboard:summary:{tenant_id}"
    try:
        raw = await redis.get(key)
    except RedisError:
        logger.warning("dashboard_cache_read_failed")
        raw = None
    if raw is not None:
        try:
            return DashboardSummary.model_validate_json(raw)
        except ValidationError:
            # Entries cached before a schema change are treated as a miss.
            logger.warning("dashboard_cache_entry_invalid")

    summary = await service.get_dashboard_summary(db=db, tenant_id=tenant_id)
    try:
        await redis.set(key, summary.model_dump_json(), ex=SUMMARY_CACHE_TTL_SECONDS)
    except RedisError:
        logger.warning("dashboard_cache_write_failed")
    return summary


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    db: DBWithTenantDep,
    redis: RedisDep,
    current_user: User = Depends(
        require_any_role("admin", "analyst", "viewer", "superadmin")
    ),
    tenant_id: uuid.UUID | None = Query(None),
) -> DashboardSummary:
    """Return metrics for the caller's tenant or an explicit superadmin target."""
    if current_user.is_superadmin:
        # D3 requires superadmins to pick one tenant, never a global aggregate.
        if tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="tenant_id is required for superadmin",
            )
        effective_tenant_id = tenant_id
        existing_id = (
            await db.execute(select(Tenant.id).where(Tenant.id == effective_tenant_id))
        ).scalar_one_or_none()
        if existing_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
            )
    else:
        if tenant_id is not None and tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only view your own tenant's dashboard",
            )
        effective_tenant_id = current_user.tenant_id
        if effective_tenant_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="A tenant is required to view the dashboard",
            )

    return await _cached_summary(db, redis, effective_tenant_id)
