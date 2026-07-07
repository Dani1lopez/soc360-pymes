"""Authentication dependencies: OAuth2 scheme, current user, role guards."""
from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_tenant_context
from app.core.logging import get_logger
from app.core.redis import check_redis_healthy, get_redis
from app.core.security import decode_access_token, has_minimum_role, is_token_revoked
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

logger = get_logger(__name__)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> User:
    try:
        payload = decode_access_token(token)
    except InvalidTokenError:
        logger.warning("auth_failed", reason="invalid_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")

    if not user_id:
        logger.warning("auth_failed", reason="missing_sub")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        logger.warning("auth_failed", reason="invalid_user_id", user_id=user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    jti = payload.get("jti")
    if not await check_redis_healthy(redis):
        logger.error("redis_unhealthy", reason="auth_dependency")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Servicio temporalmente no disponible",
        )
    if not jti or await is_token_revoked(jti, redis):
        logger.warning("auth_failed", reason="revoked_token", jti=jti)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token revocado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Temporarily elevate to superadmin so RLS allows the user lookup.
    # set_tenant_context will re-set the correct tenant context below.
    # Single roundtrip combines both set_config calls.
    await db.execute(
        text(
            "SELECT "
            "set_config('app.is_superadmin', 'true', true), "
            "set_config('app.current_tenant', '', true)"
        )
    )
    result = await db.execute(
        select(User, Tenant)
        .outerjoin(Tenant, User.tenant_id == Tenant.id)
        .where(User.id == user_uuid)
    )
    row = result.one_or_none()

    if not row or not row.User.is_active:
        logger.warning("auth_failed", reason="user_inactive", user_id=str(user_uuid))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = row.User

    if not user.is_superadmin:
        if not row.Tenant or not row.Tenant.is_active:
            logger.warning("auth_failed", reason="tenant_inactive", tenant_id=str(user.tenant_id))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant inactivo o no encontrado",
                headers={"WWW-Authenticate": "Bearer"},
            )
    if user.is_superadmin:
        await set_tenant_context(db, user.tenant_id, True)
    elif user.tenant_id is None:
        logger.warning("auth_failed", reason="missing_tenant_id", user_id=str(user_uuid))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo",
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        await set_tenant_context(db, user.tenant_id, False)

    user.current_jti = jti
    return user


def require_role(minimum_role: str):
    async def _check(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if not has_minimum_role(current_user.role, minimum_role):
            logger.warning(
                "auth_failed",
                reason="insufficient_role",
                user_id=str(current_user.id),
                actual=current_user.role,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permisos insuficientes"
            )
        return current_user
    return _check


async def require_superadmin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Permite el acceso solo a usuarios con is_superadmin=True"""
    if not current_user.is_superadmin:
        logger.warning(
            "auth_failed",
            reason="not_superadmin",
            user_id=str(current_user.id),
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de superadmin",
        )
    return current_user
