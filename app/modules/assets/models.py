from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Slice 1 (F2): `name` was renamed to `value` to align with the new
    # public-API field; the historical `hostname` column is gone. The check
    # constraint now accepts six asset_types: hostname, domain, ip, web_app,
    # subnet, cloud_resource. The DB migration that introduces these
    # changes is `20260906_2009_align_assets_model_for_slice_1_e0eafdf389fc`.
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    asset_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
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
            "asset_type IN ('hostname', 'domain', 'ip', 'web_app', "
            "'subnet', 'cloud_resource')",
            name="chk_assets_asset_type",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'archived')",
            name="chk_assets_status",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_assets_id_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "asset_type",
            "value",
            name="uq_assets_tenant_type_value",
        ),
    )

    def __repr__(self) -> str:
        return f"<Asset id={self.id} " f"type={self.asset_type!r} value={self.value!r}>"
