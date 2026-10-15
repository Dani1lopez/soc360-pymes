"""Ownership declarations: the persisted proof a scan is allowed to run (H2)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# ``declaration`` covers assets where no technical check is possible (SSH, MySQL,
# internal ranges); the other two are the DNS TXT and HTTP file challenges.
DECLARATION_METHODS = ("declaration", "dns_txt", "http_file")
DECLARATION_STATUSES = ("pending", "verified", "revoked", "failed")

_TABLE = "asset_ownership_declarations"


class AssetOwnershipDeclaration(Base):
    """One tenant's claim of ownership over one asset (S5/S6)."""

    __tablename__ = _TABLE

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    # No single-column ForeignKey: the composite constraint below binds the asset
    # to the same tenant, so a declaration can never point at somebody else's asset.
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Who declared it (S6, auditable record). Nullable so removing a user account
    # does not erase the declaration itself; the rows keep their timestamp.
    declared_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The answer recorded when the challenge was verified. The executor re-resolves
    # the target and rejects the scan when the current answer differs (D3).
    resolved_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "method IN ('declaration', 'dns_txt', 'http_file')",
            name=f"chk_{_TABLE}_method",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'revoked', 'failed')",
            name=f"chk_{_TABLE}_status",
        ),
        ForeignKeyConstraint(
            ["asset_id", "tenant_id"],
            ["assets.id", "assets.tenant_id"],
            ondelete="CASCADE",
            name="fk_asset_ownership_declarations_asset_tenant",
        ),
        Index(f"ix_{_TABLE}_tenant_id", "tenant_id"),
        # Covers asset_id lookups too, being its leading column.
        Index(f"ix_{_TABLE}_asset_tenant", "asset_id", "tenant_id"),
        Index(f"ix_{_TABLE}_declared_by_user_id", "declared_by_user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AssetOwnershipDeclaration id={self.id} asset_id={self.asset_id} "
            f"method={self.method!r} status={self.status!r}>"
        )
