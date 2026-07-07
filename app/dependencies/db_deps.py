"""Database session dependency with tenant context."""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, set_tenant_context
from app.dependencies.auth import get_current_user
from app.modules.users.models import User


async def get_db_with_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AsyncGenerator[AsyncSession, None]:
    await set_tenant_context(
        db=db,
        tenant_id=current_user.tenant_id,
        is_superadmin=current_user.is_superadmin,
    )
    yield db
