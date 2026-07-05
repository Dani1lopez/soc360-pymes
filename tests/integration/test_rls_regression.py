from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.database import set_tenant_context
from tests.conftest import TENANT_A_ID

pytestmark = pytest.mark.integration


async def test_set_tenant_context_superadmin_single_roundtrip(
    db_session: AsyncSession,
) -> None:
    """Superadmin RLS context must be set in one database roundtrip."""
    engine = db_session.bind
    assert isinstance(engine, AsyncEngine)

    statements: list[str] = []

    def capture_statement(
        _conn,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        await set_tenant_context(db_session, tenant_id=None, is_superadmin=True)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)

    set_config_queries = [query for query in statements if "set_config" in query]
    assert len(set_config_queries) == 1, (
        f"Expected 1 roundtrip, got {len(set_config_queries)}: {set_config_queries}"
    )
    assert "is_superadmin" in set_config_queries[0]
    assert "current_tenant" in set_config_queries[0]


async def test_superadmin_context_does_not_leak_to_next_tenant_request(
    db_session: AsyncSession,
) -> None:
    """Tenant context must clear any prior superadmin flag on the same session."""
    tenant_id = UUID(TENANT_A_ID)

    # Reproduce el riesgo: una request superadmin seguida por una request tenant
    # sobre la misma sesión/conexión no debe heredar permisos globales.
    await set_tenant_context(db_session, tenant_id=None, is_superadmin=True)
    await set_tenant_context(db_session, tenant_id=tenant_id, is_superadmin=False)

    result = await db_session.execute(text("SELECT current_setting('app.is_superadmin')"))

    assert result.scalar_one() == "false"
