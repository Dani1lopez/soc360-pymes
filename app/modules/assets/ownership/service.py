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
from app.modules.assets.ownership.verifiers import (
    HttpFetch,
    TxtLookup,
    target_fingerprint,
    verify_dns_txt,
    verify_http_file,
)
from app.modules.scans.targets import Resolver


class OwnershipAssetNotFoundError(Exception):
    """The asset does not exist, or is not visible to this caller."""


class OwnershipDeclarationNotFoundError(Exception):
    """The asset has no declaration to revoke."""


class OwnershipDeclarationRevokedError(Exception):
    """The declaration was revoked, so it cannot be verified."""


class OwnershipNotVerifiableError(Exception):
    """The method needs no challenge: a declaration is approved, not verified."""


class OwnershipNotApprovableError(Exception):
    """The newest declaration is a challenge: only its token can verify it."""


class OwnershipDeclarationNotPendingError(Exception):
    """The newest declaration is not pending, so there is nothing to approve."""


class OwnershipChallengeFailedError(Exception):
    """The published challenge does not contain the token."""


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

    Every method starts ``pending`` (S1/H1). ``method="declaration"`` is the
    layer S5 defines for assets where no technical check is possible (SSH, MySQL,
    internal ranges), so it is authorized by a superadmin through
    :func:`approve_ownership` instead of being trusted on creation. The DNS TXT
    and HTTP file methods are authorized by their challenge (H2-T6).
    """
    asset = await assets_service.get_asset(asset_id, tenant_id, db)
    if asset is None:
        raise OwnershipAssetNotFoundError(str(asset_id))

    declaration = AssetOwnershipDeclaration(
        tenant_id=asset.tenant_id,
        asset_id=asset.id,
        declared_value=asset.value,
        declared_by_user_id=declared_by_user_id,
        method=method,
        token=_new_token(),
        status="pending",
        verified_at=None,
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


async def verify_ownership(
    asset_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
    txt_lookup: TxtLookup | None = None,
    http_fetch: HttpFetch | None = None,
    resolver: Resolver | None = None,
) -> AssetOwnershipDeclaration:
    """Run the published challenge and record its answer (decision D3).

    A satisfied challenge marks the declaration verified and stores the
    resolved fingerprint of the target, which the executor re-checks on every
    claim. A failed challenge marks the declaration failed; the caller decides
    how to report it.
    """
    declarations = await list_declarations(asset_id, tenant_id=tenant_id, db=db)
    if not declarations:
        raise OwnershipDeclarationNotFoundError(str(asset_id))

    declaration = declarations[0]
    if declaration.status == "revoked":
        raise OwnershipDeclarationRevokedError(str(declaration.id))
    if declaration.method == "declaration":
        raise OwnershipNotVerifiableError(str(declaration.id))
    if declaration.status == "verified":
        return declaration

    asset = await assets_service.get_asset(asset_id, tenant_id, db)
    if asset is None:  # pragma: no cover - list_declarations already scoped it
        raise OwnershipAssetNotFoundError(str(asset_id))

    if declaration.method == "dns_txt":
        published = await verify_dns_txt(
            asset.asset_type, asset.value, declaration.token, lookup=txt_lookup
        )
    else:
        published = await verify_http_file(
            asset.asset_type, asset.value, declaration.token, fetch=http_fetch
        )

    if not published:
        declaration.status = "failed"
        await db.flush()
        raise OwnershipChallengeFailedError(str(declaration.id))

    declaration.status = "verified"
    declaration.verified_at = datetime.now(timezone.utc)
    declaration.resolved_fingerprint = await target_fingerprint(
        asset.asset_type, asset.value, resolver=resolver
    )
    await db.flush()
    return declaration


async def approve_ownership(
    asset_id: uuid.UUID,
    *,
    approved_by_user_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> AssetOwnershipDeclaration:
    """Approve the newest hand declaration of one visible asset (S1/H1).

    A ``method="declaration"`` row is a claim, not a proof, so a superadmin has
    to turn it into the ``verified`` row the scan gate requires, and the approval
    records who did it and when. Only that method is approvable: ``dns_txt`` and
    ``http_file`` are verified by publishing the token, and approving one by hand
    would let an operator claim an asset without publishing anything.

    The approval is one transition, not an idempotent write: a declaration that
    is already verified leaves nothing pending, so asking again is a 404.
    """
    declarations = await list_declarations(asset_id, tenant_id=tenant_id, db=db)
    if not declarations:
        raise OwnershipDeclarationNotFoundError(str(asset_id))

    declaration = declarations[0]
    if declaration.status == "revoked":
        raise OwnershipDeclarationRevokedError(str(declaration.id))
    if declaration.method != "declaration":
        raise OwnershipNotApprovableError(str(declaration.id))
    if declaration.status != "pending":
        raise OwnershipDeclarationNotPendingError(str(declaration.id))

    declaration.status = "verified"
    declaration.verified_at = datetime.now(timezone.utc)
    declaration.approved_by_user_id = approved_by_user_id
    await db.flush()
    return declaration


async def revoke_ownership(
    asset_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID | None,
    db: AsyncSession,
) -> AssetOwnershipDeclaration:
    """Revoke every declaration of one visible asset and return the newest.

    Declaring twice leaves two live rows, and the gate accepts any verified
    one, so revoking only the newest would keep authorizing scans. Idempotent:
    revoking an already revoked declaration changes nothing.
    Revoking an asset that was never declared is a 404, because there is
    nothing to revoke.
    """
    declarations = await list_declarations(asset_id, tenant_id=tenant_id, db=db)
    if not declarations:
        raise OwnershipDeclarationNotFoundError(str(asset_id))

    changed = False
    for declaration in declarations:
        if declaration.status != "revoked":
            declaration.status = "revoked"
            changed = True
    if changed:
        await db.flush()
    return declarations[0]
