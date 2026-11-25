"""Cross-tenant pre-check dependencies for admin endpoints (PR-A).

The 403 contract: a non-superadmin caller attempting to access a user or
tenant that belongs to a different tenant MUST receive HTTP 403 (not 404),
with a single `cross_tenant_access_blocked` log line at the chokepoint.
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.core.logging import get_logger
from app.dependencies.auth import get_current_user
from app.dependencies.db_deps import get_db_with_tenant
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Cross-tenant pre-check dependencies (PR-A)
#
# The 403 contract: a non-superadmin caller attempting to access a user or
# tenant that belongs to a different tenant MUST receive HTTP 403 (not 404),
# with a single `cross_tenant_access_blocked` log line at the chokepoint.
#
# Implementation notes:
# - The user Depends must ELEVATE the session to superadmin (SET LOCAL pair,
#   same pattern as get_current_user) to read the cross-tenant row
#   for the tenant_id comparison. The SET LOCAL guarantee (third arg `true`)
#   means the elevation is transaction-local and cannot leak across pooled
#   connections — see `set_tenant_context` in app/core/database.py.
# - After the pre-check, we restore the caller's canonical context via
#   `set_tenant_context` so the service-layer mutation runs under the
#   caller's tenant (R05).
# - The tenant Depends does NOT need elevation for the cross-tenant 403
#   path: the comparison runs in Python on the URL id, before any SELECT
#   (this is the inversion called out in the design, section 2).
# ---------------------------------------------------------------------------


def _log_cross_tenant_attempt(
    caller_id: uuid.UUID,
    target_id: uuid.UUID,
    method: str,
    endpoint: str,
) -> None:
    """Single chokepoint for the 403 log line (OQ-1).

    The same helper covers both user-targeting and tenant-targeting
    attempts. `target_id` is whichever id the pre-check operated on
    (a user id for the user Depends, a tenant id for the tenant Depends).
    NO `tenant_id` field — sensitive info avoidance.
    """
    logger.warning(
        "cross_tenant_access_blocked",
        caller_id=str(caller_id),
        target_id=str(target_id),
        method=method,
        endpoint=endpoint,
    )


async def _get_user_for_admin(
    user_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    *,
    method: str,
    endpoint: str,
) -> User:
    """Cross-tenant pre-check for user-targeting endpoints (R01-R03, R05).

    Returns the User row pre-validated for the caller:
    - Superadmin: row fetched under the existing superadmin context.
    - Same-tenant: row fetched under the caller's tenant (RLS allows).
    - Cross-tenant (non-superadmin): row fetched under temporary
      superadmin elevation, compared, 403 raised on mismatch.

    After a successful pre-check the caller's tenant context is restored
    so the downstream service mutation runs under the canonical RLS scope.
    """
    # Superadmin path: no extra elevation needed. `get_db_with_tenant`
    # already established the superadmin context via `get_current_user`.
    if current_user.is_superadmin:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )
        return row

    # Non-superadmin cross-tenant pre-check: elevate to read the row,
    # compare tenant_id, restore canonical context. Modeled on
    # `get_current_user` SET LOCAL pair.
    await db.execute(
        text(
            "SELECT "
            "set_config('app.is_superadmin', 'true', true), "
            "set_config('app.current_tenant', '', true)"
        )
    )
    try:
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        row = result.scalar_one_or_none()
    finally:
        # Always restore — SET LOCAL is cleared on COMMIT/ROLLBACK, but
        # we re-set the canonical context so the next statement in the
        # request runs under the caller's tenant.
        await set_tenant_context(
            db=db,
            tenant_id=current_user.tenant_id,
            is_superadmin=False,
        )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    if row.tenant_id != current_user.tenant_id:
        _log_cross_tenant_attempt(
            caller_id=current_user.id,
            target_id=user_id,
            method=method,
            endpoint=endpoint,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )
    return row


def _user_for_admin(method: str):
    """Factory that builds a Depends with the right `method` log label.

    Add a new wrapper here whenever a new HTTP verb is added to user routes.
    """

    async def _dep(
        user_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_with_tenant),
    ) -> User:
        return await _get_user_for_admin(
            user_id,
            current_user,
            db,
            method=method,
            endpoint=f"/users/{user_id}",
        )

    return _dep


get_user_for_admin_get = _user_for_admin("GET")
get_user_for_admin_patch = _user_for_admin("PATCH")
get_user_for_admin_delete = _user_for_admin("DELETE")


async def _get_tenant_for_admin(
    tenant_id: uuid.UUID,
    current_user: User,
    db: AsyncSession,
    *,
    method: str,
    endpoint: str,
) -> Tenant:
    """Cross-tenant pre-check for tenant-targeting endpoints (RK-6).

    Inversion of the user Depends: the comparison target IS the URL id,
    so the mismatch check runs in Python BEFORE any DB SELECT. No
    superadmin elevation is needed for the 403 path.

    Returns the Tenant row pre-validated for the caller.
    """
    if current_user.is_superadmin:
        result = await db.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant no encontrado",
            )
        return row

    if tenant_id != current_user.tenant_id:
        _log_cross_tenant_attempt(
            caller_id=current_user.id,
            target_id=tenant_id,
            method=method,
            endpoint=endpoint,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )

    # Same-tenant path: RLS lets the SELECT through under the caller's tenant.
    result = await db.execute(
        select(Tenant).where(Tenant.id == tenant_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant no encontrado",
        )
    return row


def _tenant_for_admin(method: str):
    """Factory for the tenant Depends with the right `method` log label."""

    async def _dep(
        tenant_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_with_tenant),
    ) -> Tenant:
        return await _get_tenant_for_admin(
            tenant_id,
            current_user,
            db,
            method=method,
            endpoint=f"/tenants/{tenant_id}",
        )

    return _dep


# Tenants only have one targeted endpoint (GET /tenants/{id}) in PR-A.
# PATCH and DELETE on tenants remain superadmin-only and do not need the
# cross-tenant pre-check (the superadmin branch already covers them).
get_tenant_for_admin_get = _tenant_for_admin("GET")
