from __future__ import annotations
from datetime import datetime
from uuid import UUID as PyUUID

from typing import TYPE_CHECKING


from sqlalchemy import VARCHAR, ForeignKey, Index
from sqlalchemy.dialects.postgresql import INET, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base 

if TYPE_CHECKING:
    from app.modules.users.models import User


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    
    #Primary Key
    id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()",
    )
    
    #Foreign Key
    user_id: Mapped[PyUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    
    #Token data
    token_hash: Mapped[str] = mapped_column(
        VARCHAR(255),
        nullable=False,
        unique=True,
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
    )
    
    revoked_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
        default=None,
    )
    
    created_from_ip: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
        default=None,
    )
    
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default="NOW()",
    )
    
    #Relationship
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")
    
    #Indice parcial
    __table_args__ = (
        Index(
            "idx_refresh_active",
            "token_hash",
            postgresql_where="revoked_at IS NULL",
        ),
    )