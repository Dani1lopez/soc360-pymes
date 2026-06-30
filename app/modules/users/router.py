from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.core.exceptions import UserError
from app.core.logging import get_logger
from app.core.security import has_minimum_role
from app.dependencies import (
    AdminDep,
    DBWithTenantDep,
    CurrentUserDep,
    RedisDep,
    UserForAdminGetDep,
    UserForAdminPatchDep,
    UserForAdminDeleteDep,
)
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import RoleEnum, UserCreate, UserResponse, UserUpdate

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: CurrentUserDep,
) -> User:
    """Devuelve el perfil del usuario autenticado"""
    return current_user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    db: DBWithTenantDep,
    current_user: AdminDep,
) -> User:
    """Crea un nuevo usuario"""
    if not current_user.is_superadmin:
        if body.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo los superadmins pueden crear otros superadmin",
            )
        if body.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes crear usuarios en tu propio tenant.",
            )
        if body.role in (RoleEnum.admin, RoleEnum.superadmin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes asignar un rol igual o superior al tuyo",
            )
    try:
        user = await service.create_user(data=body, db=db)
    except UserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    logger.info("user_created", user_id=str(user.id), created_by=str(current_user.id))
    return user


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: DBWithTenantDep,
    current_user: AdminDep,
    tenant_id: uuid.UUID | None = Query(None, description="Filtrar por tenant (solo superadmin)"),
    include_inactive: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> list[User]:
    """Lista de usuarios"""
    if current_user.is_superadmin:
        effective_tenant_id = tenant_id
    else:
        if tenant_id is not None and tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes listar usuarios de tu propio tenant",
            )
        effective_tenant_id = current_user.tenant_id

    return await service.list_users(
        db=db,
        tenant_id=effective_tenant_id,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user: UserForAdminGetDep,
    current_user: CurrentUserDep,
) -> User:
    """Obtiene un usuario por ID.

    The cross-tenant pre-check fires inside the Depends (R01, R04, R05).
    A same-tenant admin or the user themselves can read; cross-tenant
    access returns 403 with a `cross_tenant_access_blocked` log line.
    """
    # Self-read is always allowed
    if user.id == current_user.id:
        return user
    # Superadmin can read anyone
    if current_user.is_superadmin:
        return user
    # Otherwise, same-tenant admin can read (Depends already verified
    # tenant match, so we only need the role check here)
    if has_minimum_role(current_user.role, "admin"):
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permisos insuficientes",
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    body: UserUpdate,
    current_user: CurrentUserDep,
    target: UserForAdminPatchDep,
    db: DBWithTenantDep,
    redis: RedisDep,
) -> User:
    """Actualiza un usuario.

    The cross-tenant pre-check fires inside the Depends (R02, R04, R05).
    The in-router policy checks (self-deactivation 409, role hierarchy
    403, admin-modifies-superadmin 403) STAY HERE — they are policy
    rules, not tenant rules.
    """
    is_self = target.id == current_user.id

    if current_user.is_superadmin:
        if is_self and body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No puedes desactivarte a ti mismo",
            )

    elif is_self:
        # Un usuario solo puede cambiar su email y nombre, no su rol ni estado
        if body.role is not None or body.is_active is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes cambiar tu propio rol o estado de activación",
            )

    elif has_minimum_role(current_user.role, "admin"):
        if target.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes modificar a un superadmin.",
            )
        if body.role is not None and has_minimum_role(body.role.value, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No puedes elegir un rol igual o superior al tuyo",
            )
        if body.is_active is not None and has_minimum_role(target.role, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Un admin no puede cambiar el estado de activación de otro admin",
            )

    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )

    try:
        user = await service.update_user(
            current_user=current_user,
            target=target,
            data=body,
            db=db,
            redis=redis,
        )
    except UserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    logger.info("user_updated", user_id=str(target.id), updated_by=str(current_user.id))
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def deactivate_user(
    current_user: AdminDep,
    target: UserForAdminDeleteDep,
    db: DBWithTenantDep,
    redis: RedisDep,
) -> None:
    """Desactiva un usuario y revoca todas sus sesiones.

    The cross-tenant pre-check fires inside the Depends (R03, R04, R05).
    The in-router policy checks (self-deactivation 409, superadmin
    deactivation 403, admin-deactivates-admin 403) STAY HERE — they
    are policy rules, not tenant rules.
    """
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No puedes desactivarte a ti mismo",
        )

    if not current_user.is_superadmin:
        if target.is_superadmin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No se puede desactivar a un superadmin",
            )
        if has_minimum_role(target.role, "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Un admin no puede desactivar a otro admin",
            )

    try:
        await service.deactivate_user(
            current_user=current_user,
            target=target,
            db=db,
            redis=redis,
        )
    except UserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    logger.info("user_deactivated", user_id=str(target.id), deactivated_by=str(current_user.id))
