"""Lock-aware database dependencies for deactivation routes."""

from __future__ import annotations

from typing import AsyncGenerator
from uuid import UUID

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dist_lock import acquire_dist_lock
from app.core.outage import (
    _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK,
    _FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK,
)
from app.core.redis import get_redis
from app.dependencies.cross_tenant import get_user_for_admin_delete
from app.dependencies.db_deps import get_db_with_tenant
from app.modules.users.models import User


async def get_user_deactivation_db(
    db: AsyncSession = Depends(get_db_with_tenant),
    target: User = Depends(get_user_for_admin_delete),
    redis: Redis = Depends(get_redis),
) -> AsyncGenerator[AsyncSession, None]:
    """Hold the user deactivation lease through commit or rollback."""
    async with acquire_dist_lock(
        flow_id=_FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK,
        tenant_id=str(target.tenant_id),
        asset_id=f"user:{target.id}",
        operation="deactivate",
        ttl_seconds=settings.LOCK_DEFAULT_TTL_SECONDS,
        wait_timeout_seconds=2.0,
        redis=redis,
    ):
        try:
            yield db
        except BaseException:
            await db.rollback()
            raise
        else:
            await db.commit()


async def get_tenant_deactivation_db(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AsyncGenerator[AsyncSession, None]:
    """Hold the tenant deactivation lease through commit or rollback."""
    async with acquire_dist_lock(
        flow_id=_FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK,
        tenant_id=str(tenant_id),
        asset_id=f"tenant:{tenant_id}",
        operation="deactivate",
        ttl_seconds=settings.LOCK_DEFAULT_TTL_SECONDS,
        wait_timeout_seconds=2.0,
        redis=redis,
    ):
        try:
            yield db
        except BaseException:
            await db.rollback()
            raise
        else:
            await db.commit()
