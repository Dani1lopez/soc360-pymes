from __future__ import annotations

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
# Per-connection safety nets (issue #134): statement_timeout kills runaway
# queries; lock_timeout prevents indefinite waits on row/table locks.
# asyncpg forwards server_settings to PostgreSQL in the startup packet so
# every connection inherits these limits automatically.


def _build_connect_args(stmt_timeout_ms: int, lock_timeout_ms: int) -> dict:
    """Build asyncpg connect_args with server_settings for timeouts.

    Extracted as a pure function so it can be tested without reloading the
    module or monkeypatching SQLAlchemy internals.
    """
    return {
        "server_settings": {
            "statement_timeout": str(stmt_timeout_ms),
            "lock_timeout": str(lock_timeout_ms),
        },
    }


engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=1800,
    connect_args=_build_connect_args(
        settings.DB_STATEMENT_TIMEOUT_MS,
        settings.DB_LOCK_TIMEOUT_MS,
    ),
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
    """Apply RLS context for the current request.

    Sets the Postgres session variables that drive RLS policies:
    - `app.current_tenant` — the tenant_id of the requester (or '' if superadmin)
    - `app.is_superadmin` — whether the requester bypasses RLS

    When `is_superadmin=True`, this function ALSO clears any previous
    `app.current_tenant` value to prevent session poisoning across pooled
    connections. This is critical: without the clear, a superadmin query
    that follows a regular tenant query on the same connection would be
    silently filtered by the previous tenant's RLS policy.

    Both set_config calls run in a single roundtrip to minimize latency.
    """
    if not is_superadmin and tenant_id is None:
        raise ValueError("tenant_id requerido para usuarios no superadmin")

    if is_superadmin:
        # Single roundtrip: set superadmin flag AND clear current_tenant to prevent
        # session poisoning across pooled connections.
        await db.execute(
            text(
                "SELECT "
                "set_config('app.is_superadmin', 'true', true), "
                "set_config('app.current_tenant', '', true)"
            )
        )
    else:
        await db.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        await db.execute(text("SELECT set_config('app.is_superadmin', 'false', true)"))
    
    logger.debug(
        "tenant_context_set", 
        tenant_id=str(tenant_id) if tenant_id else "ALL",
        is_superadmin=is_superadmin
    )

#Para celery workers y scripts
@asynccontextmanager
async def get_session_with_tenant(
    tenant_id: UUID | None,
    is_superadmin: bool = False,
) -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id, is_superadmin)
            yield session


# Solo para /health y /auth/login - el resto usa get_db_with_tenant()
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Sesión SIN contexto de tenant.

    USAR SOLO EN:
      - GET /health
      - POST /auth/login
      - POST /auth/refresh

    NUNCA usar en endpoints que accedan a datos de tenant.
    Para esos usar get_db_with_tenant() en dependencies.py
    """
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session