from __future__ import annotations

import re
import uuid
import unicodedata
from typing import Any
import asyncio

from redis.asyncio import Redis
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import TenantError
from app.core.security import revoke_all_user_access_tokens
from app.modules.auth.service import _revoke_all_user_tokens_for_tenant
from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantCreate, TenantUpdate, TenantSettings
from app.modules.users.models import User


_PLAN_MAX_ASSETS: dict[str, int] = {
    "free": 10,
    "starter": 25,
    "pro": 100,
    "enterprise": 500,
}


def _generate_slug(name: str) -> str:
    slug = unicodedata.normalize("NFKD", name)
    slug = slug.encode("ascii", "ignore").decode("ascii")
    slug = slug.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)   # elimina puntuación
    slug = re.sub(r"[\s_]+", "-", slug)     # espacios → guiones
    slug = re.sub(r"-+", "-", slug)         # guiones múltiples → uno
    slug = slug.strip("-")
    if not slug:
        raise TenantError("El nombre no produce un slug válido", status_code=400)
    return slug[:100]    


def _plan_to_max_assets(plan: str) -> int:
    """Devuelve el limite de assets para un plan"""
    if plan not in _PLAN_MAX_ASSETS:
        raise TenantError(f"Plan inválido: {plan!r}", status_code=400)
    return _PLAN_MAX_ASSETS[plan]


async def _is_slug_taken(
    db: AsyncSession,
    slug: str,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Comprueba si el slug ya está en uso"""
    stmt = select(func.count()).select_from(Tenant).where(Tenant.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Tenant.id != exclude_id)
    result = await db.execute(stmt)
    return (result.scalar_one() or 0) > 0


async def create_tenant(data: TenantCreate, db: AsyncSession) -> Tenant:
    """Crea un nuevo tenant"""
    if data.slug:
        if await _is_slug_taken(db, data.slug):
            raise TenantError("El slug ya esta en uso.", status_code=409)
        slug = data.slug
    else:
        base_slug = _generate_slug(data.name)
        slug = base_slug
        suffix = 2
        MAX_SLUG_ATTEMPTS = 100
        while await _is_slug_taken(db, slug):
            if suffix > MAX_SLUG_ATTEMPTS:
                raise TenantError("No se pudo generar un slug único para este nombre.", status_code=409)
            slug = f"{base_slug}-{suffix}"
            suffix += 1
    
    raw_settings: dict[str, Any] = data.settings.model_dump() if data.settings is not None else {}
    validated_settings = TenantSettings.model_validate(raw_settings).model_dump()
    
    tenant = Tenant(
        name=data.name.strip(),
        slug=slug,
        plan=data.plan,
        is_active=True,
        max_assets=_plan_to_max_assets(data.plan),
        settings=validated_settings,
    )
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)
    return tenant


async def get_tenant_by_id(tenant_id: uuid.UUID, db: AsyncSession) -> Tenant | None:
    """Devuelve el tenant o None si no existe"""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def list_tenants(
    db: AsyncSession,
    include_inactive: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> list[Tenant]:
    """Lista de tenants"""
    limit = min(limit, 200)
    stmt = select(Tenant)
    if not include_inactive:
        stmt = stmt.where(Tenant.is_active == True)# noqa: E712
    stmt = stmt.order_by(Tenant.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_tenant(
    tenant_id: uuid.UUID,
    data: TenantUpdate,
    db: AsyncSession,
    redis: Redis,
) -> Tenant:
    """Actualiza el tenant"""
    tenant = await get_tenant_by_id(tenant_id, db)
    if tenant is None:
        raise TenantError("Tenant no encontrado", status_code=404)

    update_data = data.model_dump(exclude_unset=True)

    # Detectar transición de activo → inactivo ANTES de aplicar cambios
    is_deactivating = (
        "is_active" in update_data
        and update_data["is_active"] is False
        and tenant.is_active is True
    )

    # Detectar transición de inactivo → activo para reactivar usuarios del tenant
    is_reactivating = (
        "is_active" in update_data
        and update_data["is_active"] is True
        and tenant.is_active is False
    )

    if "name" in update_data:
        tenant.name = update_data["name"].strip()

    if "plan" in update_data:
        tenant.plan = update_data["plan"]
        if "max_assets" not in update_data:
            tenant.max_assets = _plan_to_max_assets(update_data["plan"])

    if "max_assets" in update_data:
        tenant.max_assets = update_data["max_assets"]

    if "is_active" in update_data:
        tenant.is_active = update_data["is_active"]

    if "settings" in update_data:
        current = TenantSettings.model_validate(tenant.settings or {})

        merged = current.model_dump()
        merged.update(update_data["settings"])
        tenant.settings = TenantSettings.model_validate(merged).model_dump()

    await db.flush()

    if is_reactivating:
        await db.execute(
            update(User)
            .where(User.tenant_id == tenant_id)
            .values(is_active=True)
        )

    # Revocar tokens solo si hubo transición True → False
    if is_deactivating:
        # Desactivar todos los usuarios del tenant
        await db.execute(
            update(User)
            .where(User.tenant_id == tenant_id)
            .values(is_active=False)
        )

        # Revocar todos los refresh tokens de los usuarios del tenant (DB)
        await _revoke_all_user_tokens_for_tenant(tenant_id, db)

        # Revocar todos los access tokens de los usuarios del tenant (Redis denylist)
        user_ids = (await db.scalars(
            select(User.id).where(User.tenant_id == tenant_id)
        )).all()
        await asyncio.gather(*[
            revoke_all_user_access_tokens(
                user_id=str(uid),
                redis=redis,
                ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            )
            for uid in user_ids
        ])

    await db.refresh(tenant)
    return tenant


async def deactivate_tenant(
    tenant_id: uuid.UUID,
    db: AsyncSession,
    redis: Redis,
) -> Tenant:
    """Desactiva el tenant, sus usuarios, y revoca todas las sesiones"""
    tenant = await get_tenant_by_id(tenant_id, db)
    if tenant is None:
        raise TenantError("Tenant no encontrado", status_code=404)
    if not tenant.is_active:
        raise TenantError("El tenant ya esta desactivado", status_code=409)
    tenant.is_active = False

    # Desactivar todos los usuarios del tenant
    await db.execute(
        update(User)
        .where(User.tenant_id == tenant_id)
        .values(is_active=False)
    )

    # Revocar todos los refresh tokens de los usuarios del tenant (DB)
    await _revoke_all_user_tokens_for_tenant(tenant_id, db)

    # Revocar todos los access tokens de los usuarios del tenant (Redis denylist)
    user_ids = (await db.scalars(
        select(User.id).where(User.tenant_id == tenant_id)
    )).all()
    await asyncio.gather(*[
        revoke_all_user_access_tokens(
            user_id=str(uid),
            redis=redis,
            ttl_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )
        for uid in user_ids
    ])

    await db.flush()
    await db.refresh(tenant)
    return tenant
