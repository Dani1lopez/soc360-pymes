from uuid import UUID
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

#Evita timeouts de firewalls que cierran conexiones inactivas
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
)

#expire_on_commit=False: necesario en async - lazy loading no existe
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass


async def set_tenant_context(
    db: AsyncSession,
    tenant_id: UUID | None,
    is_superadmin: bool = False,
) -> None:
    """Activa RLS para la transacción actual. SET LOCAL se limpia solo al hacer el commit"""
    if not is_superadmin and tenant_id is None:
        raise ValueError("tenant_id requerido para usuarios no superadmin")
    
    await db.execute(
        text("SET LOCAL app.current_tenant = :tenant_id"),
        {"tenant_id": str(tenant_id) if tenant_id else ""},
    )
    
    await db.execute(
        text("SET LOCAL app.is_superadmin = :is_superadmin"),
        {"is_superadmin": "true" if is_superadmin else "false"},
    )
    
    logger.debug("tenant_context_set", tenant_id=str(tenant_id) or "ALL", is_superadmin=is_superadmin)

#Para celery workers y scripts
@asynccontextmanager
async def get_session_with_tenant(
    tenant_id: UUID | None,
    is_superadmin: bool = False,
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id, is_superadmin)
            try:
                yield session
            except Exception:
                await session.rollback()
                raise


#Solo para /health y /auth/login - el resto usa get_db_with _tenant()
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise