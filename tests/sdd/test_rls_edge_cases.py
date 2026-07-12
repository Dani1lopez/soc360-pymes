"""Edge-case RLS behaviour tests.

Covers spec requirements #2–#8:
  #2  Cross-tenant FK rejection
  #3  Malicious tenant_id UPDATE blocked
  #4  Absent / empty / invalid tenant context fails closed
  #5  Pooled connection context does not leak
  #6  Superadmin context cleanup is correct
  #7  refresh_tokens isolation through users subquery
  #8  Cascade isolation respects tenant boundaries

RED phase: all tests expected to fail under superuser role.
GREEN phase: after CI hardening, all MUST pass.
"""

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from tests.conftest import ADMIN_B_ID, TENANT_A_ID, TENANT_B_ID


# ===========================================================================
# #2 — Cross-tenant foreign-key rejection
# ===========================================================================


@pytest.mark.asyncio
async def test_cross_tenant_fk_vulnerability_scan(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """INSERT vulnerability with scan_id from Tenant B raises FK violation."""
    from sqlalchemy.exc import IntegrityError

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    scan_b_id = seed_two_tenants["scans"]["tenant_b"]

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO vulnerabilities "
                "(id, tenant_id, scan_id, title, severity, status) "
                "VALUES (gen_random_uuid(), :tenant, :scan_id, "
                "'Cross-tenant vuln', 'high', 'open')"
            ),
            {"tenant": UUID(TENANT_A_ID), "scan_id": scan_b_id},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_cross_tenant_fk_report_asset(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """INSERT report with asset_id from Tenant B raises FK violation."""
    from sqlalchemy.exc import IntegrityError

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    asset_b_id = seed_two_tenants["assets"]["tenant_b"]

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO reports "
                "(id, tenant_id, asset_id, name, report_type, status) "
                "VALUES (gen_random_uuid(), :tenant, :asset_id, "
                "'Cross-tenant report', 'vulnerability', 'pending')"
            ),
            {"tenant": UUID(TENANT_A_ID), "asset_id": asset_b_id},
        )
        await db_session.flush()


@pytest.mark.asyncio
async def test_cross_tenant_fk_scan_asset(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """INSERT scan with asset_id from Tenant B raises FK violation."""
    from sqlalchemy.exc import IntegrityError

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    asset_b_id = seed_two_tenants["assets"]["tenant_b"]

    with pytest.raises(IntegrityError):
        await db_session.execute(
            text(
                "INSERT INTO scans "
                "(id, tenant_id, asset_id, name, scan_type, status) "
                "VALUES (gen_random_uuid(), :tenant, :asset_id, "
                "'Cross-tenant scan', 'vulnerability', 'pending')"
            ),
            {"tenant": UUID(TENANT_A_ID), "asset_id": asset_b_id},
        )
        await db_session.flush()


# ===========================================================================
# #3 — Malicious tenant_id UPDATE blocked
# ===========================================================================


@pytest.mark.asyncio
async def test_malicious_tenant_id_update(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Moving a row to another tenant is blocked by the RLS WITH CHECK policy.

    Uses `assets` (a simple tenant_id FK to tenants, with NO composite parent
    FK) so the only mechanism that can reject the UPDATE is the RLS policy —
    this isolates RLS from foreign-key enforcement. Tenant B exists, so the FK
    is satisfied and cannot mask an RLS failure the way the vulnerabilities
    composite FK would.
    """
    from sqlalchemy.exc import ProgrammingError

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    asset_a_id = seed_two_tenants["assets"]["tenant_a"]

    with pytest.raises(ProgrammingError):
        await db_session.execute(
            text("UPDATE assets SET tenant_id = :new_tenant WHERE id = :asset_id"),
            {"new_tenant": UUID(TENANT_B_ID), "asset_id": asset_a_id},
        )
        await db_session.flush()
    await db_session.rollback()
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)


# ===========================================================================
# #4 — Absent / empty / invalid tenant context fails closed
# ===========================================================================


@pytest.mark.asyncio
async def test_no_context_returns_zero(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Without SET LOCAL, any query returns zero rows.

    The seed_two_tenants fixture runs inside the same transaction and sets
    is_superadmin=True via SET LOCAL (transaction-scoped GUC). Override
    both GUCs to empty to simulate a fresh session without context.
    """
    await db_session.execute(text("SELECT set_config('app.is_superadmin', '', true)"))
    await db_session.execute(text("SELECT set_config('app.current_tenant', '', true)"))
    result = await db_session.execute(
        text("SELECT id FROM assets WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_A_ID)},
    )
    rows = result.fetchall()
    assert len(rows) == 0, (
        f"No-context query returned {len(rows)} rows — " "should fail closed"
    )


@pytest.mark.asyncio
async def test_empty_context_returns_zero(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """SET LOCAL app.current_tenant = '' → zero rows."""
    await db_session.execute(text("SELECT set_config('app.current_tenant', '', true)"))
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'false', true)")
    )
    result = await db_session.execute(
        text("SELECT id FROM assets WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_A_ID)},
    )
    rows = result.fetchall()
    assert len(rows) == 0, (
        f"Empty-context query returned {len(rows)} rows — " "should fail closed"
    )


@pytest.mark.asyncio
async def test_invalid_context_returns_zero(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """SET LOCAL app.current_tenant = 'malicious' → zero rows."""
    await db_session.execute(
        text("SELECT set_config('app.current_tenant', 'malicious', true)")
    )
    await db_session.execute(
        text("SELECT set_config('app.is_superadmin', 'false', true)")
    )
    result = await db_session.execute(
        text("SELECT id FROM assets WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_A_ID)},
    )
    rows = result.fetchall()
    assert len(rows) == 0, (
        f"Invalid-context query returned {len(rows)} rows — " "should fail closed"
    )


# ===========================================================================
# #5 — Pooled connection context does not leak
# ===========================================================================


@pytest.mark.asyncio
async def test_pooled_context_does_not_leak(
    pooled_engine,
    isolated_db_session,
    seed_two_tenants: dict,
):
    """After committing Tenant A context, a fresh session has none."""
    # Session 1: set Tenant A context and commit
    # isolated_db_session is a synchronous factory, not an async one
    session1 = isolated_db_session()
    async with session1.begin():
        await set_tenant_context(session1, UUID(TENANT_A_ID), is_superadmin=False)
        await session1.execute(text("SELECT 1"))
    await session1.close()

    # Session 2 (same pool): should have NO inherited context
    session2 = isolated_db_session()
    async with session2.begin():
        result = await session2.execute(
            text("SELECT current_setting('app.current_tenant', true)")
        )
        tenant_val = result.scalar()
        assert (
            tenant_val is None or tenant_val == ""
        ), f"app.current_tenant leaked: {tenant_val!r}"

        result = await session2.execute(
            text("SELECT current_setting('app.is_superadmin', true)")
        )
        super_val = result.scalar()
        assert (
            super_val is None or super_val == ""
        ), f"app.is_superadmin leaked: {super_val!r}"

        # NOTE: a data-visibility assertion here would be vacuous — the
        # seed_two_tenants rows are written on the NullPool db_session inside an
        # uncommitted transaction, so this separate pooled connection can never
        # see them regardless of RLS context. The GUC-leak assertions above are
        # the meaningful check for connection-pool context bleed.
    await session2.close()


# ===========================================================================
# #6 — Superadmin context cleanup is correct
# ===========================================================================


@pytest.mark.asyncio
async def test_superadmin_transition_sequence(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """superadmin → A → superadmin → B → only B visible."""
    # Step 1: superadmin sees everything
    r1 = await db_session.execute(
        text(
            "SELECT set_config('app.is_superadmin', 'true', true), "
            "set_config('app.current_tenant', '', true)"
        )
    )
    r1.fetchall()  # consume result to avoid ResourceClosedError on next execute
    r2 = await db_session.execute(text("SELECT COUNT(*) FROM vulnerabilities"))
    total = r2.scalar()
    assert (
        total is not None and total >= 2
    ), f"Superadmin should see all vulnerabilities, got {total}"

    # Step 2: Tenant A sees only Tenant A rows
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    r3 = await db_session.execute(
        text("SELECT id FROM vulnerabilities WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_A_ID)},
    )
    a_rows = r3.fetchall()
    assert len(a_rows) >= 1

    r4 = await db_session.execute(
        text("SELECT id FROM vulnerabilities WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_B_ID)},
    )
    b_rows_in_a = r4.fetchall()
    assert len(b_rows_in_a) == 0

    # Step 3: superadmin again — consume the set_tenant_context result
    r5 = await db_session.execute(
        text(
            "SELECT set_config('app.is_superadmin', 'true', true), "
            "set_config('app.current_tenant', '', true)"
        )
    )
    r5.fetchall()  # consume result to avoid ResourceClosedError on next execute
    r6 = await db_session.execute(text("SELECT COUNT(*) FROM vulnerabilities"))
    total2 = r6.scalar()
    assert total2 is not None and total2 >= 2

    # Step 4: Tenant B — only Tenant B rows visible
    await set_tenant_context(db_session, UUID(TENANT_B_ID), is_superadmin=False)
    r7 = await db_session.execute(
        text("SELECT id FROM vulnerabilities WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_B_ID)},
    )
    b_rows = r7.fetchall()
    assert len(b_rows) >= 1

    r8 = await db_session.execute(
        text("SELECT id FROM vulnerabilities WHERE tenant_id = :tid"),
        {"tid": UUID(TENANT_A_ID)},
    )
    a_rows_in_b = r8.fetchall()
    assert (
        len(a_rows_in_b) == 0
    ), f"Tenant B should not see Tenant A rows, got {len(a_rows_in_b)}"


# ===========================================================================
# #7 — refresh_tokens isolation through users subquery
# ===========================================================================


@pytest.mark.asyncio
async def test_refresh_tokens_isolation(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Tenant A cannot access Tenant B refresh tokens."""
    from sqlalchemy.exc import IntegrityError, ProgrammingError

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    rt_b_id = seed_two_tenants["refresh_tokens"]["tenant_b"]

    # SELECT — should return zero rows
    result = await db_session.execute(
        text(
            "SELECT rt.id FROM refresh_tokens rt "
            "JOIN users u ON u.id = rt.user_id "
            "WHERE u.tenant_id = :tid"
        ),
        {"tid": UUID(TENANT_B_ID)},
    )
    assert (
        len(result.fetchall()) == 0
    ), "Tenant A should not see Tenant B refresh tokens"

    # INSERT — blocked by RLS WITH CHECK (InsufficientPrivilege) or by the FK
    # to the Tenant B user, which is invisible under Tenant A context.
    with pytest.raises((IntegrityError, ProgrammingError)):
        await db_session.execute(
            text(
                "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) "
                "VALUES (:uid, 'hash_test', '2030-01-01T00:00:00Z')"
            ),
            {"uid": UUID(ADMIN_B_ID)},
        )
        await db_session.flush()
    await db_session.rollback()
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)


# ===========================================================================
# #8 — Cascade isolation respects tenant boundaries
# ===========================================================================


@pytest.mark.asyncio
async def test_cascade_isolation(
    db_session: AsyncSession,
    seed_two_tenants: dict,
):
    """Tenant A DELETE on Tenant B asset affects zero rows (no cascade)."""
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    asset_b_id = seed_two_tenants["assets"]["tenant_b"]

    # Attempt to delete Tenant B's asset while scoped to Tenant A
    result = await db_session.execute(
        text("DELETE FROM assets WHERE id = :asset_id"),
        {"asset_id": asset_b_id},
    )
    await db_session.flush()
    assert result.rowcount == 0, (
        f"DELETE on Tenant B asset from Tenant A session affected "
        f"{result.rowcount} rows — RLS should have blocked it"
    )

    # Verify Tenant B's data is intact (use superadmin to check)
    await set_tenant_context(db_session, None, is_superadmin=True)
    result = await db_session.execute(
        text("SELECT id FROM assets WHERE id = :asset_id"),
        {"asset_id": asset_b_id},
    )
    assert (
        result.fetchone() is not None
    ), "Tenant B asset should still exist after blocked delete"
