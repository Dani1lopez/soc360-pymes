"""The authorization gate: is this asset legitimately scannable? (H2).

Two layers call this, for different guarantees:

* ``dispatch_scan``, before it fixes ``dispatched_at`` — the early guarantee that
  an undeclared scan never becomes claimable.
* the executor, before it builds the scan graph — the mandatory guarantee, since
  it is the only code that runs on every claim, so a declaration revoked after
  dispatch still blocks the scan.

The claim itself (``claim_next_scan``) carries no gate: it is a blind cross-tenant
UPDATE, and joining here would defeat its purpose.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assets.ownership.models import AssetOwnershipDeclaration

# Stable, persistable failure reason (also the API detail for the dispatch gate).
NOT_VERIFIED_REASON = "asset ownership is not verified"


class OwnershipRequiredError(Exception):
    """The asset has no verified ownership declaration."""

    reason = NOT_VERIFIED_REASON

    def __init__(self) -> None:
        super().__init__(NOT_VERIFIED_REASON)


async def has_verified_declaration(db: AsyncSession, *, asset_id: uuid.UUID) -> bool:
    """Whether the asset has a verified declaration visible to this session.

    The query runs under the session's RLS context, so the caller's tenant scope
    applies: a declaration of another tenant is not visible and does not count.
    """
    stmt = (
        select(AssetOwnershipDeclaration.id)
        .where(
            AssetOwnershipDeclaration.asset_id == asset_id,
            AssetOwnershipDeclaration.status == "verified",
        )
        .limit(1)
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def ensure_scan_authorized(db: AsyncSession, *, asset_id: uuid.UUID) -> None:
    """Raise :class:`OwnershipRequiredError` when the asset may not be scanned."""
    if not await has_verified_declaration(db, asset_id=asset_id):
        raise OwnershipRequiredError()
