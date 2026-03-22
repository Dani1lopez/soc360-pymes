from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UserError
from app.core.logging import get_logger
from app.core.security import has_minimum_role
from app.dependencies import (
    get_current_user,
    get_db_with_tenant,
    require_role,
)
from app.modules.users import service
from app.modules.users.models import User
from app.modules.users.schemas import RoleEnum, UserCreate, UserResponse, UserUpdate

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: User = Depends(get_current_user),
) -> User:
    """Devuelve el perfil del usuario autenticado"""
    return current_user


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_with_tenant),
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
    tenant_id: uuid.UUID | None = Query(None, description="Filtrar por tenant (solo superadmin)"),
    include_inactive: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_with_tenant),
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
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> User:
    """Obtiene un usuario por ID"""
    user = await service.get_user_by_id(user_id=user_id, db=db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    
    #El propio usuario siempre puede verse a si mismo
    if user.id == current_user.id:
        return user
    
    if current_user.is_superadmin:
        return user
    
    if(
        has_minimum_role(current_user.role, "admin")
        and user.tenant_id == current_user.tenant_id
    ):
        return user
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permisos insuficientes",
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> User:
    """Actualiza un usuario"""
    target = await service.get_user_by_id(user_id=user_id, db=db)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    
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
        if target.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes modificar usuarios de tu propio tenant",
            )
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
    
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permisos insuficientes",
        )
    
    try:
        user = await service.update_user(user_id=user_id, data=body, db=db)
    except UserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    
    logger.info("user_updated", user_id=str(user_id), updated_by=str(current_user.id))
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def deactivate_user(
    user_id: uuid.UUID,
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> None:
    """Desactiva un usuario"""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No puedes desactivarte a ti mismo",
        )
    
    target = await service.get_user_by_id(user_id=user_id, db=db)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    
    if not current_user.is_superadmin:
        if target.tenant_id != current_user.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo puedes desactivar usuarios de tu propio tenant",
            )
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
        await service.deactivate_user(user_id=user_id, db=db)
    except UserError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    
    logger.info("user_deactivated", user_id=str(user_id), deactivated_by=str(current_user.id))