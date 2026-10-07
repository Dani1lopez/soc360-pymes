"""PostgreSQL index definitions backing dashboard aggregations."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INDEX_CASES = [
    pytest.param(
        "vulnerabilities",
        "ix_vulnerabilities_tenant_status_severity",
        "(tenant_id, status, severity)",
        None,
        id="tenant-status-severity",
    ),
    pytest.param(
        "vulnerabilities",
        "ix_vulnerabilities_tenant_created_at",
        "(tenant_id, created_at)",
        None,
        id="tenant-created-at",
    ),
    pytest.param(
        "vulnerabilities",
        "ix_vulnerabilities_tenant_closed_at",
        "(tenant_id, closed_at)",
        "closed_at IS NOT NULL",
        id="tenant-closed-at",
    ),
    pytest.param(
        "scans",
        "ix_scans_tenant_completed_at",
        "(tenant_id, completed_at)",
        None,
        id="tenant-completed-at",
    ),
]


@pytest.mark.parametrize("table,index_name,columns,predicate", INDEX_CASES)
async def test_dashboard_aggregation_index_definition(
    db_session: AsyncSession,
    table: str,
    index_name: str,
    columns: str,
    predicate: str | None,
) -> None:
    indexdef = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = :table AND indexname = :index_name"
            ),
            {"table": table, "index_name": index_name},
        )
    ).scalar_one_or_none()
    assert indexdef is not None, f"Missing index: {index_name}"
    assert f"USING btree {columns}" in indexdef
    assert "UNIQUE" not in indexdef
    if predicate is None:
        assert "WHERE" not in indexdef
    else:
        assert indexdef.split("WHERE", 1)[-1].strip() == f"({predicate})"
