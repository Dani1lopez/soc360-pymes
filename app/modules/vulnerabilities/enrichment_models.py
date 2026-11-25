from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ENRICHMENT_FUNCTIONS = (
    "executive_summary",
    "technical_description",
    "exploitability",
    "contextual_severity",
    "remediation",
    "business_impact",
    "references",
    "mitigation_plan",
    "hardening",
)
ENRICHMENT_STATUSES = ("pending", "ok", "failed")


class VulnerabilityEnrichment(Base):
    __tablename__ = "vulnerability_enrichments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    vulnerability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    function: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default="pending"
    )
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "vulnerability_id", "function",
            name="uq_vulnerability_enrichments_vulnerability_function",
        ),
        CheckConstraint(
            "function IN (" + ", ".join(repr(v) for v in ENRICHMENT_FUNCTIONS) + ")",
            name="chk_vulnerability_enrichments_function",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(repr(v) for v in ENRICHMENT_STATUSES) + ")",
            name="chk_vulnerability_enrichments_status",
        ),
        CheckConstraint("attempts >= 0", name="chk_vulnerability_enrichments_attempts"),
        ForeignKeyConstraint(
            ["vulnerability_id", "tenant_id"],
            ["vulnerabilities.id", "vulnerabilities.tenant_id"],
            ondelete="CASCADE",
            name="fk_vulnerability_enrichments_vulnerability_tenant",
        ),
        Index(
            "ix_vulnerability_enrichments_vulnerability_tenant",
            "vulnerability_id", "tenant_id",
        ),
    )

    def __repr__(self) -> str:
        return f"<VulnerabilityEnrichment id={self.id} function={self.function!r}>"
