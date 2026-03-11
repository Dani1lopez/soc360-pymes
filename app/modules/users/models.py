from datetime import datetime, timezone
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    
    __table_args__ = (
        CheckConstraint(
            "NOT (is_superadmin = TRUE AND tenant_id IS NOT NULL)",
            name="chk_superadmin_no_tenant",
        ),
        CheckConstraint(
            "NOT (is_superadmin = FALSE AND tenant_id IS NULL)",
            name="chk_user_has_tenant",
        ),
        CheckConstraint(
            "role IN ('viewer', 'analyst', 'ingestor', 'admin', 'superadmin')",
            name="chk_valid_role",
        ),
    )
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    
    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email!r} role={self.role!r}>"