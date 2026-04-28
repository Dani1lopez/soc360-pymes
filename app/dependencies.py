from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated, TypeAlias, AsyncGenerator

from app.core.database import get_db, set_tenant_context
from app.core.redis import get_redis, get_redis_client, check_redis_healthy
from app.core.security import decode_access_token, is_token_revoked, has_minimum_role
from app.core.llm import get_llm_provider, LLMProvider
from app.modules.users.models import User
from app.modules.tenants.models import Tenant
from app.core.logging import get_logger
logger = get_logger(__name__)

_event_bus: "EventBus | None" = None


async def get_event_bus() -> "EventBus":
    """Singleton factory for the EventBus dependency."""
    global _event_bus
    if _event_bus is None:
        from app.event_bus import EventBus
        redis = await get_redis_client()
        _event_bus = EventBus(redis)
    return _event_bus


async def get_llm() -> LLMProvider:
    """FastAPI dependency: return the singleton LLM provider for this request."""
    return get_llm_provider()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> User:
    try:
        payload = decode_access_token(token)
    except JWTError:
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


async def get_db_with_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSession, None]:
    await set_tenant_context(
        db=db,
        tenant_id=current_user.tenant_id,
        is_superadmin=current_user.is_superadmin,
    )
    yield db



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


# ---------------------------------------------------------------------------
# FastAPI dependency type aliases — modern Annotated pattern
# Defined AFTER all dependency functions so they are in scope
# ---------------------------------------------------------------------------
DBDep: TypeAlias = Annotated[AsyncSession, Depends(get_db)]
RedisDep: TypeAlias = Annotated[Redis, Depends(get_redis)]
CurrentUserDep: TypeAlias = Annotated[User, Depends(get_current_user)]
SuperadminDep: TypeAlias = Annotated[User, Depends(require_superadmin)]
DBWithTenantDep: TypeAlias = Annotated[AsyncSession, Depends(get_db_with_tenant)]
