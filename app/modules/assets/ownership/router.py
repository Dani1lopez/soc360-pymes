"""Ownership declaration endpoints (H2-T3), under ``/api/v1/assets``.

RBAC mirrors the asset matrix: declaring and revoking need ``admin`` or
``superadmin``; reading follows the asset read allowlist. The caller's tenant
scope is applied through the asset lookup, so an invisible asset is a 404.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import DBDep
from app.dependencies.auth import require_any_role
from app.modules.assets.ownership import service
from app.modules.assets.ownership.schemas import (
    OwnershipDeclarationListResponse,
    OwnershipDeclarationRequest,
    OwnershipDeclarationResponse,
)
from app.modules.users.models import User

router = APIRouter(prefix="/assets", tags=["asset-ownership"])

WriteRole = Annotated[User, Depends(require_any_role("admin", "superadmin"))]
ReadRole = Annotated[
    User, Depends(require_any_role("admin", "analyst", "viewer", "superadmin"))
]


@router.post(
    "/{asset_id}/ownership",
    response_model=OwnershipDeclarationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Declare ownership of an asset",
)
async def declare_ownership(
    asset_id: uuid.UUID,
    payload: OwnershipDeclarationRequest,
    db: DBDep,
    current_user: WriteRole,
) -> OwnershipDeclarationResponse:
    try:
        declaration = await service.declare_ownership(
            asset_id,
            method=payload.method,
            declared_by_user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            db=db,
        )
    except service.OwnershipAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    return OwnershipDeclarationResponse.model_validate(declaration)


@router.get(
    "/{asset_id}/ownership",
    response_model=OwnershipDeclarationListResponse,
    summary="List the ownership declarations of an asset",
)
async def list_declarations(
    asset_id: uuid.UUID,
    db: DBDep,
    current_user: ReadRole,
) -> OwnershipDeclarationListResponse:
    try:
        declarations = await service.list_declarations(
            asset_id, tenant_id=current_user.tenant_id, db=db
        )
    except service.OwnershipAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    items = [
        OwnershipDeclarationResponse.model_validate(declaration)
        for declaration in declarations
    ]
    return OwnershipDeclarationListResponse(items=items, total=len(items))


@router.post(
    "/{asset_id}/ownership/revoke",
    response_model=OwnershipDeclarationResponse,
    summary="Revoke the newest ownership declaration of an asset",
)
async def revoke_ownership(
    asset_id: uuid.UUID,
    db: DBDep,
    current_user: WriteRole,
) -> OwnershipDeclarationResponse:
    try:
        declaration = await service.revoke_ownership(
            asset_id, tenant_id=current_user.tenant_id, db=db
        )
    except service.OwnershipAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except service.OwnershipDeclarationNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="ownership declaration not found"
        ) from exc
    return OwnershipDeclarationResponse.model_validate(declaration)
