"""Ownership declaration endpoints (H2-T3), under ``/api/v1/assets``.

RBAC mirrors the asset matrix: declaring and revoking need ``admin`` or
``superadmin``; reading follows the asset read allowlist. Approving a hand
declaration is a ``superadmin`` decision only (S1/H1), so a tenant admin can
never authorize their own claim. The caller's tenant scope is applied through
the asset lookup, so an invisible asset is a 404.
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
from app.modules.assets.ownership.verifiers import (
    HttpFetch,
    TxtLookup,
    fetch_well_known_file,
    lookup_txt_records,
)
from app.modules.users.models import User
from app.modules.scans.targets import Resolver, TargetRejectedError

router = APIRouter(prefix="/assets", tags=["asset-ownership"])

WriteRole = Annotated[User, Depends(require_any_role("admin", "superadmin"))]
ApproveRole = Annotated[User, Depends(require_any_role("superadmin"))]
ReadRole = Annotated[
    User, Depends(require_any_role("admin", "analyst", "viewer", "superadmin"))
]


def get_txt_lookup() -> TxtLookup:
    """The real DNS TXT lookup; tests override this dependency."""
    return lookup_txt_records


def get_http_fetch() -> HttpFetch:
    """The real challenge fetch; tests override this dependency."""
    return fetch_well_known_file


def get_target_resolver() -> Resolver | None:
    """The resolver used for the fingerprint. ``None`` means the real one."""
    return None


TxtLookupDep = Annotated[TxtLookup, Depends(get_txt_lookup)]
HttpFetchDep = Annotated[HttpFetch, Depends(get_http_fetch)]
ResolverDep = Annotated[Resolver | None, Depends(get_target_resolver)]


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
    "/{asset_id}/ownership/verify",
    response_model=OwnershipDeclarationResponse,
    summary="Verify the newest ownership challenge of an asset",
)
async def verify_ownership(
    asset_id: uuid.UUID,
    db: DBDep,
    current_user: WriteRole,
    txt_lookup: TxtLookupDep,
    http_fetch: HttpFetchDep,
    resolver: ResolverDep,
) -> OwnershipDeclarationResponse:
    try:
        declaration = await service.verify_ownership(
            asset_id,
            tenant_id=current_user.tenant_id,
            db=db,
            txt_lookup=txt_lookup,
            http_fetch=http_fetch,
            resolver=resolver,
        )
    except (
        service.OwnershipAssetNotFoundError,
        service.OwnershipDeclarationNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=404, detail="ownership declaration not found"
        ) from exc
    except service.OwnershipDeclarationRevokedError as exc:
        raise HTTPException(
            status_code=409, detail="ownership declaration is revoked"
        ) from exc
    except service.OwnershipNotVerifiableError as exc:
        raise HTTPException(
            status_code=409, detail="ownership declaration needs no verification"
        ) from exc
    except service.OwnershipChallengeFailedError as exc:
        raise HTTPException(
            status_code=400, detail="ownership challenge not satisfied"
        ) from exc
    except TargetRejectedError as exc:
        # The published name resolved to a target the scan policy refuses, so the
        # fingerprint that authorizes scans cannot be recorded. That is a client
        # mistake with a stable reason, not a server failure (M4/S4).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"target rejected: {exc.reason}",
        ) from exc
    return OwnershipDeclarationResponse.model_validate(declaration)


@router.post(
    "/{asset_id}/ownership/approve",
    response_model=OwnershipDeclarationResponse,
    summary="Approve a hand ownership declaration (superadmin only)",
)
async def approve_ownership(
    asset_id: uuid.UUID,
    db: DBDep,
    current_user: ApproveRole,
) -> OwnershipDeclarationResponse:
    """Turn a pending ``declaration`` into the verified row a scan requires.

    Only a superadmin can approve, and only the hand-declared method: the DNS
    TXT and HTTP file challenges prove ownership themselves (S1/H1).
    """
    try:
        declaration = await service.approve_ownership(
            asset_id,
            approved_by_user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            db=db,
        )
    except service.OwnershipAssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except service.OwnershipDeclarationNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="ownership declaration not found"
        ) from exc
    except service.OwnershipDeclarationNotPendingError as exc:
        raise HTTPException(
            status_code=404, detail="no pending ownership declaration"
        ) from exc
    except service.OwnershipDeclarationRevokedError as exc:
        raise HTTPException(
            status_code=409, detail="ownership declaration is revoked"
        ) from exc
    except service.OwnershipNotApprovableError as exc:
        raise HTTPException(
            status_code=409, detail="ownership declaration cannot be approved"
        ) from exc
    return OwnershipDeclarationResponse.model_validate(declaration)


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
