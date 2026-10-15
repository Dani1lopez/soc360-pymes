"""Ownership declaration service: the record that authorizes a scan (H2).

The declaration belongs to the **asset's** tenant, never to the caller's, so the
superadmin path cannot record a claim under the wrong tenant.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets import service as assets_service
from app.modules.assets.ownership.models import AssetOwnershipDeclaration


class OwnershipAssetNotFoundError(Exception):
    """The asset does not exist, or is not visible to this caller."""


class OwnershipDeclarationNotFoundError(Exception):
    """The asset has no declaration to revoke."""


def _new_token() -> str:
    """A per-declaration challenge token, also used by the DNS/HTTP methods."""
    return secrets.token_urlsafe(32)


async def declare_ownership(
    asset_id: uuid.UUID,
    *,
    method: str,
    declared_by_user_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> AssetOwnershipDeclaration:
    """Record a declaration for one visible asset.

    ``method="declaration"`` is the layer S5 defines for assets where no
    technical check is possible (SSH, MySQL, internal ranges), so it is
    authorized as soon as it is recorded. The DNS TXT and HTTP file methods
    start as ``pending`` until their challenge is verified (H2-T6).
    """
    asset = await assets_service.get_asset(asset_id, tenant_id, db)
    if asset is None:
        raise OwnershipAssetNotFoundError(str(asset_id))

    declared = method == "declaration"
    declaration = AssetOwnershipDeclaration(
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        declared_by_user_id=declared_by_user_id,
        method=method,
        token=_new_token(),
        status="verified" if declared else "pending",
        verified_at=datetime.now(timezone.utc) if declared else None,
    )
    db.add(declaration)
    await db.flush()
    return declaration


async def list_declarations(
    asset_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> list[AssetOwnershipDeclaration]:
    """Return every declaration of one visible asset, newest first."""
    asset = await assets_service.get_asset(asset_id, tenant_id, db)
    if asset is None:
        raise OwnershipAssetNotFoundError(str(asset_id))

    stmt = (
        select(AssetOwnershipDeclaration)
        .where(AssetOwnershipDeclaration.asset_id == asset.id)
        .order_by(
            AssetOwnershipDeclaration.created_at.desc(),
            AssetOwnershipDeclaration.id.desc(),
        )
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_ownership(
    asset_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> AssetOwnershipDeclaration:
    """Revoke the newest declaration of one visible asset.

    Idempotent: revoking an already revoked declaration returns it unchanged.
    Revoking an asset that was never declared is a 404, because there is
    nothing to revoke.
    """
    declarations = await list_declarations(asset_id, tenant_id=tenant_id, db=db)
    if not declarations:
        raise OwnershipDeclarationNotFoundError(str(asset_id))

    declaration = declarations[0]
    if declaration.status != "revoked":
        declaration.status = "revoked"
        await db.flush()
    return declaration
