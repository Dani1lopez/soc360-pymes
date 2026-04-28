from __future__ import annotations

import uuid

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import UserError
from app.core.security import hash_password, revoke_all_user_access_tokens
from app.modules.auth.service import _revoke_all_user_tokens
from app.modules.tenants.models import Tenant
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate


async def _is_email_taken(
    db: AsyncSession,
    email: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Comprueba si el email ya existe"""
    stmt = (
        select(func.count())
        .select_from(User)
        .where(func.lower(User.email) == email.lower())
    )
    if exclude_id is not None:
        stmt = stmt.where(User.id != exclude_id)
    result = await db.execute(stmt)
    return (result.scalar_one() or 0) > 0


async def _get_active_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID,
) -> Tenant:
    """Devuelva el tenant si existe y esta activo, o lanza UserError"""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise UserError("Tenant no encontrado", status_code=404)
    if not tenant.is_active:
        raise UserError("El tenant está inactivo", status_code=409)
    return tenant


async def create_user(data: UserCreate, db: AsyncSession) -> User:
    """Crea un nuevo usuario"""
    if await _is_email_taken(db, data.email):
        raise UserError("El email ya está registrado", status_code=409)
    
    if not data.is_superadmin and data.tenant_id is not None:
        await _get_active_tenant(db, data.tenant_id)
    
    user = User(
        tenant_id=data.tenant_id,
        email=data.email.lower().strip(),
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role.value,
        is_active=True,
        is_superadmin=data.is_superadmin,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def get_user_by_id(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> User | None:
    """Devuelve el usuario o None si no existe"""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_email(
    email: str,
    db: AsyncSession,
) -> User | None:
    """Devuelve el usuario por email o None"""
    result = await db.execute(
        select(User).where(func.lower(User.email) == email.lower())
    )
    return result.scalar_one_or_none()


async def list_users(
    db: AsyncSession,
    tenant_id: uuid.UUID | None = None,
    include_inactive: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> list[User]:
    """Lista de usuarios"""
    limit = min(limit, 200)
    stmt = select(User)
    if tenant_id is not None:
        stmt = stmt.where(User.tenant_id == tenant_id)
    if not include_inactive:
        stmt = stmt.where(User.is_active == True) # noqa: E712
    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_user(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession,
    redis: Redis,
) -> User:
    """Actualiza campos del usuario"""
    user = await get_user_by_id(user_id, db)
    if user is None:
        raise UserError("Usuario no encontrado", status_code=404)

    update_data = data.model_dump(exclude_unset=True)

    # Detectar transición de activo → inactivo ANTES de aplicar cambios
    is_deactivating = (
        "is_active" in update_data
        and update_data["is_active"] is False
        and user.is_active is True
    )

    if "email" in update_data:
        new_email = update_data["email"].lower().strip()
        if await _is_email_taken(db, new_email, exclude_id=user_id):
            raise UserError("El email ya esta registrado", status_code=409)
        user.email = new_email

    if "full_name" in update_data:
        user.full_name = update_data["full_name"].strip()

    if "role" in update_data:
        user.role = update_data["role"].value

    if "is_active" in update_data:
        user.is_active = update_data["is_active"]

    await db.flush()

    # Revocar tokens solo si hubo transición True → False
    if is_deactivating:
        await _revoke_all_user_tokens(user_id, db)
        await revoke_all_user_access_tokens(
            user_id=str(user_id),
            redis=redis,
            ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    await db.refresh(user)
    return user


async def deactivate_user(
    user_id: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Desactiva el usuario y revoca todas sus sesiones activas"""
    user = await get_user_by_id(user_id, db)
    if user is None:
        raise UserError("Usuario no encontrado", status_code=404)
    if not user.is_active:
        raise UserError("El usuario ya está desactivado", status_code=409)
    user.is_active = False
    await db.flush()

    # Revocar todos los refresh tokens del usuario (DB)
    await _revoke_all_user_tokens(user_id, db)

    # Revocar todos los access tokens del usuario (Redis denylist)
    await revoke_all_user_access_tokens(
        user_id=str(user_id),
        redis=redis,
        ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )