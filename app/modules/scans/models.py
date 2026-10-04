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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Scan(Base):
    __tablename__ = "scans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    scan_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Set by the run trigger on enqueue; NULL means never dispatched.
    # Used for the daily quota and the reaper.
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Slice 5 (F2) executor outcome columns. ``failure_reason`` is a short,
    # bounded machine reason (``timeout``, ``connect_fallback``, ...) set only
    # when the scan ends ``failed``; ``raw_output`` holds the raw nmap XML.
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
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
            "scan_type IN ('discovery', 'vulnerability', 'web', 'full')",
            name="chk_scans_scan_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="chk_scans_status",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_scans_id_tenant_id"),
        ForeignKeyConstraint(
            ["asset_id", "tenant_id"],
            ["assets.id", "assets.tenant_id"],
            ondelete="CASCADE",
            name="fk_scans_asset_tenant",
        ),
        Index("ix_scans_asset_tenant", "asset_id", "tenant_id"),
        Index("ix_scans_tenant_dispatched_at", "tenant_id", "dispatched_at"),
        Index(
            "ix_scans_ready",
            "dispatched_at",
            "id",
            postgresql_where="status = 'pending' AND dispatched_at IS NOT NULL",
        ),
        # Slice 2 business rule: at most one OPEN definition per
        # (tenant_id, asset_id, name). The index is partial on purpose — the
        # name is released as soon as the scan leaves ``pending``, so an asset
        # can be re-scanned under the same name after a run finishes. A plain
        # unique constraint would reserve the name forever instead.
        Index(
            "uq_scans_tenant_asset_name_pending",
            "tenant_id",
            "asset_id",
            "name",
            unique=True,
            postgresql_where="status = 'pending'",
        ),
    )

    def __repr__(self) -> str:
        return f"<Scan id={self.id} name={self.name!r}>"
