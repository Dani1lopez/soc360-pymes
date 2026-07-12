"""Cross-tenant CRUD denial tests for all 7 RLS-protected tables.

Spec requirement #1: A session scoped to Tenant A MUST NOT be able to
SELECT / INSERT / UPDATE / DELETE rows belonging to Tenant B.

RED phase: all 14 parametrized test cases expected to fail when the
database session connects as a superuser (current CI setup), because
superuser bypasses RLS entirely.

GREEN phase: after CI hardening (WU-6) sets soc360_app as NOSUPERUSER
NOBYPASSRLS, these tests MUST all pass.
"""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from tests.conftest import ADMIN_B_ID, TENANT_A_ID, TENANT_B_ID
from tests.sdd.conftest import PROTECTED_TABLES


# ---------------------------------------------------------------------------
# Helper: build dynamic SELECT / INSERT / UPDATE / DELETE statements
# ---------------------------------------------------------------------------


def _select_b_tenant_rows(table: str) -> str:
    """Return SELECT that would match Tenant B rows."""
    if table == "tenants":
        return f"SELECT id FROM {table} WHERE id = '{TENANT_B_ID}'"
    elif table == "users":
        return f"SELECT id FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    elif table == "refresh_tokens":
        # refresh_tokens has no tenant_id; filter via users subquery
        return (
            f"SELECT rt.id FROM {table} rt "
            f"JOIN users u ON u.id = rt.user_id "
            f"WHERE u.tenant_id = '{TENANT_B_ID}'"
        )
    else:
        return f"SELECT id FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"


def _insert_b_row(table: str, seed: dict) -> str | None:
    """Return INSERT for a Tenant B row (to verify RLS blocks it).

    `seed` is the dict produced by `seed_two_tenants` with shape:
        seed["<table>"]["tenant_a" | "tenant_b"] -> UUID

    Tables that reference parent rows owned by Tenant B (scans -> assets,
    vulnerabilities -> scans, reports -> assets, refresh_tokens -> users) use
    the seeded Tenant B IDs so the FK is logically valid; the INSERT itself
    must still be rejected because the session is scoped to Tenant A and the
    RLS WITH CHECK policy does not allow Tenant B ownership.
    """
    if table == "tenants":
        return (
            f"INSERT INTO {table} (id, name, slug, plan, is_active, max_assets) "
            f"VALUES ('{UUID('33333333-3333-3333-3333-333333333333')}', "
            f"'Tenant C', 'tenant-c', 'free', true, 10)"
        )
    elif table == "users":
        return (
            f"INSERT INTO {table} (id, tenant_id, email, hashed_password, "
            f"full_name, role, is_active, is_superadmin) "
            f"VALUES ('{UUID('44444444-4444-4444-4444-444444444444')}', "
            f"'{TENANT_B_ID}', 'intruder@evil.test', 'hash', "
            f"'Intruder', 'viewer', true, false)"
        )
    elif table == "refresh_tokens":
        # INSERT owned by Tenant B's admin user — FK to users holds; RLS on
        # refresh_tokens (which scopes by users.tenant_id) must reject.
        return (
            f"INSERT INTO {table} (id, user_id, token_hash, expires_at) "
            f"VALUES (gen_random_uuid(), '{ADMIN_B_ID}', "
            f"'intruder_refresh_hash', '2030-01-01T00:00:00Z')"
        )
    elif table == "assets":
        return (
            f"INSERT INTO {table} (id, tenant_id, name, hostname, asset_type, status) "
            f"VALUES ('{UUID('55555555-5555-5555-5555-555555555555')}', "
            f"'{TENANT_B_ID}', 'Intruder Asset', 'intruder-host', 'host', 'active')"
        )
    elif table == "scans":
        return (
            f"INSERT INTO {table} (id, tenant_id, asset_id, name, scan_type, status) "
            f"VALUES (gen_random_uuid(), '{TENANT_B_ID}', "
            f"'{seed['assets']['tenant_b']}', "
            f"'Intruder Scan', 'vulnerability', 'pending')"
        )
    elif table == "vulnerabilities":
        return (
            f"INSERT INTO {table} (id, tenant_id, scan_id, title, severity, status) "
            f"VALUES (gen_random_uuid(), '{TENANT_B_ID}', "
            f"'{seed['scans']['tenant_b']}', "
            f"'Intruder Vuln', 'high', 'open')"
        )
    elif table == "reports":
        return (
            f"INSERT INTO {table} (id, tenant_id, asset_id, name, report_type, status) "
            f"VALUES (gen_random_uuid(), '{TENANT_B_ID}', "
            f"'{seed['assets']['tenant_b']}', "
            f"'Intruder Report', 'vulnerability', 'pending')"
        )
    return None


def _update_b_rows(table: str) -> str | None:
    """Return UPDATE targeting Tenant B rows."""
    if table == "tenants":
        return f"UPDATE {table} SET name = 'hacked' WHERE id = '{TENANT_B_ID}'"
    elif table == "users":
        return (
            f"UPDATE {table} SET full_name = 'hacked' "
            f"WHERE tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "refresh_tokens":
        return (
            f"UPDATE {table} rt SET revoked_at = NOW() "
            f"FROM users u WHERE u.id = rt.user_id "
            f"AND u.tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "assets":
        return (
            f"UPDATE {table} SET name = 'hacked' " f"WHERE tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "scans":
        return (
            f"UPDATE {table} SET name = 'hacked' " f"WHERE tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "vulnerabilities":
        return (
            f"UPDATE {table} SET title = 'hacked' " f"WHERE tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "reports":
        return (
            f"UPDATE {table} SET name = 'hacked' " f"WHERE tenant_id = '{TENANT_B_ID}'"
        )
    return None


def _delete_b_rows(table: str) -> str | None:
    """Return DELETE targeting Tenant B rows."""
    if table == "tenants":
        return f"DELETE FROM {table} WHERE id = '{TENANT_B_ID}'"
    elif table == "users":
        return f"DELETE FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    elif table == "refresh_tokens":
        return (
            f"DELETE FROM {table} rt USING users u "
            f"WHERE u.id = rt.user_id AND u.tenant_id = '{TENANT_B_ID}'"
        )
    elif table == "assets":
        return f"DELETE FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    elif table == "scans":
        return f"DELETE FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    elif table == "vulnerabilities":
        return f"DELETE FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    elif table == "reports":
        return f"DELETE FROM {table} WHERE tenant_id = '{TENANT_B_ID}'"
    return None


# ---------------------------------------------------------------------------
# Parametrized tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
@pytest.mark.asyncio
async def test_cross_tenant_select_returns_zero(
    table_name: str,
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Tenant A SELECT on Tenant B rows returns zero rows."""
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    stmt = text(_select_b_tenant_rows(table_name))
    result = await db_session.execute(stmt)
    rows = result.fetchall()
    assert len(rows) == 0, (
        f"SELECT on {table_name} returned {len(rows)} rows for Tenant B "
        f"when scoped to Tenant A (RLS bypassed?)"
    )


@pytest.mark.parametrize("table_name", PROTECTED_TABLES)
@pytest.mark.asyncio
async def test_cross_tenant_write_blocked(
    table_name: str,
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Tenant A cannot INSERT/UPDATE/DELETE Tenant B rows.

    Tests INSERT, UPDATE, and DELETE for each table. For INSERT we are
    strict: an RLS rejection MUST surface as SQLSTATE 42501
    (insufficient_privilege). Generic IntegrityError (unique/unrelated FK) or
    broken SQL would otherwise be silently accepted as "RLS enforcement",
    which masks real regressions.
    """
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)

    # --- INSERT ---
    insert_sql = _insert_b_row(table_name, seed_two_tenants)
    if insert_sql is not None:
        from sqlalchemy.exc import DBAPIError

        try:
            result = await db_session.execute(text(insert_sql))
            await db_session.flush()
        except DBAPIError as exc:
            await db_session.rollback()
            await set_tenant_context(
                db_session, UUID(TENANT_A_ID), is_superadmin=False
            )
            sqlstate = getattr(exc.orig, "sqlstate", None)
            assert sqlstate == "42501", (
                f"INSERT on {table_name} was rejected with SQLSTATE "
                f"{sqlstate!r}, expected '42501' (RLS insufficient_privilege). "
                f"A generic constraint error does not prove RLS enforcement."
            )
        else:
            assert result.rowcount == 0, (
                f"INSERT on {table_name} affected {result.rowcount} rows "
                f"for Tenant B when scoped to Tenant A (RLS bypassed?)"
            )

    # --- UPDATE ---
    update_sql = _update_b_rows(table_name)
    if update_sql is not None:
        result = await db_session.execute(text(update_sql))
        await db_session.flush()
        assert result.rowcount == 0, (
            f"UPDATE on {table_name} affected {result.rowcount} rows "
            f"for Tenant B when scoped to Tenant A"
        )

    # --- DELETE ---
    delete_sql = _delete_b_rows(table_name)
    if delete_sql is not None:
        result = await db_session.execute(text(delete_sql))
        await db_session.flush()
        assert result.rowcount == 0, (
            f"DELETE on {table_name} affected {result.rowcount} rows "
            f"for Tenant B when scoped to Tenant A"
        )
