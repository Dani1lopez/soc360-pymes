from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Query

from app.core.exceptions import TenantError
from app.dependencies import DBDep, CurrentUserDep, SuperadminDep, RedisDep
from app.modules.tenants import schemas, service


router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post(
    "/",
    response_model=schemas.TenantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nuevo tenant",
)
async def create_tenant(
    payload: schemas.TenantCreate,
    db: DBDep,
    current_user: SuperadminDep,
) -> schemas.TenantResponse:
    """Crea una nueva organizacion- Solo superadmin"""
    try:
        tenant = await service.create_tenant(payload, db)
    except TenantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        )
    return schemas.TenantResponse.model_validate(tenant)


@router.get(
    "/",
    response_model=list[schemas.TenantResponse],
    summary="Listar todos los tenants",
)
async def list_tenants(
    db: DBDep,
    current_user: SuperadminDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = False,
) -> list[schemas.TenantResponse]:
    """Lista paginada de tenants"""
    tenants = await service.list_tenants(db, offset=offset, include_inactive=include_inactive, limit=limit)
    return [schemas.TenantResponse.model_validate(t) for t in tenants]


@router.get(
    "/{tenant_id}",
    response_model=schemas.TenantResponse,
    summary="Obtener tenant por id",
)
async def get_tenant(
    tenant_id: UUID,
    db: DBDep,
    current_user: CurrentUserDep,
) -> schemas.TenantResponse:
    if not current_user.is_superadmin:
        if current_user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant no encontrado",
            )

    tenant = await service.get_tenant_by_id(tenant_id, db)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant no encontrado",
        )
    return schemas.TenantResponse.model_validate(tenant)


@router.patch(
    "/{tenant_id}",
    response_model=schemas.TenantResponse,
    summary="Actualizar tenant",
)
async def update_tenant(
    tenant_id: UUID,
    payload: schemas.TenantUpdate,
    db: DBDep,
    current_user: SuperadminDep,
) -> schemas.TenantResponse:
    """Actualiza campos de un tenant"""
    try:
        updated = await service.update_tenant(tenant_id, payload, db)
    except TenantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        )
    return schemas.TenantResponse.model_validate(updated)


@router.delete(
    "/{tenant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Desactivar tenant",
)
async def deactivate_tenant(
    tenant_id: UUID,
    db: DBDep,
    redis: RedisDep,
    current_user: SuperadminDep,
) -> None:
    """Desactiva un tenant, sus usuarios, y revoca todas las sesiones"""
    try:
        await service.deactivate_tenant(tenant_id, db, redis)
    except TenantError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        )
