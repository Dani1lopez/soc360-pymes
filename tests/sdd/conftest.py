"""Shared RLS test harness for SDD harden-rls-fk-indexes.

Provides:
  - PROTECTED_TABLES: list of all 7 RLS-protected table names
  - seed_two_tenants: function-scoped fixture seeding representative rows in
    every RLS-protected table for both Tenant A and Tenant B.
"""

from uuid import UUID

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.auth.models import RefreshToken
from app.modules.reports.models import Report
from app.modules.scans.models import Scan
from app.modules.vulnerabilities.models import Vulnerability

from tests.conftest import ADMIN_A_ID, ADMIN_B_ID, TENANT_A_ID, TENANT_B_ID

PROTECTED_TABLES = [
    "tenants",
    "users",
    "refresh_tokens",
    "assets",
    "scans",
    "vulnerabilities",
    "reports",
]


@pytest_asyncio.fixture
async def seed_two_tenants(
    db_session: AsyncSession,
    seed_data,
) -> dict:
    """Seed representative rows for both tenants across all RLS tables.

    Depends on the root `seed_data` fixture which already creates Tenant A,
    Tenant B, and their users. This fixture adds one row per table per tenant.

    Returns a dict with seeded row IDs keyed by table and tenant.
    """
    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=True)
    await db_session.flush()

    ids: dict[str, dict[str, UUID]] = {
        "assets": {},
        "scans": {},
        "vulnerabilities": {},
        "reports": {},
        "refresh_tokens": {},
    }

    # --- Assets ---
    asset_a_id = UUID("aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa")
    asset_b_id = UUID("bbbbbbbb-0000-0000-0000-bbbbbbbbbbbb")

    await db_session.execute(
        pg_insert(Asset)
        .values(
            id=asset_a_id,
            tenant_id=UUID(TENANT_A_ID),
            name="Alpha Asset",
            hostname="alpha-host-1",
            asset_type="host",
            status="active",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(Asset)
        .values(
            id=asset_b_id,
            tenant_id=UUID(TENANT_B_ID),
            name="Beta Asset",
            hostname="beta-host-1",
            asset_type="host",
            status="active",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()
    ids["assets"]["tenant_a"] = asset_a_id
    ids["assets"]["tenant_b"] = asset_b_id

    # --- Scans ---
    scan_a_id = UUID("aaaaaaaa-1111-0000-0000-aaaaaaaaaaaa")
    scan_b_id = UUID("bbbbbbbb-1111-0000-0000-bbbbbbbbbbbb")

    await db_session.execute(
        pg_insert(Scan)
        .values(
            id=scan_a_id,
            tenant_id=UUID(TENANT_A_ID),
            asset_id=asset_a_id,
            name="Alpha Scan",
            scan_type="vulnerability",
            status="completed",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(Scan)
        .values(
            id=scan_b_id,
            tenant_id=UUID(TENANT_B_ID),
            asset_id=asset_b_id,
            name="Beta Scan",
            scan_type="vulnerability",
            status="completed",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()
    ids["scans"]["tenant_a"] = scan_a_id
    ids["scans"]["tenant_b"] = scan_b_id

    # --- Vulnerabilities ---
    vuln_a_id = UUID("aaaaaaaa-2222-0000-0000-aaaaaaaaaaaa")
    vuln_b_id = UUID("bbbbbbbb-2222-0000-0000-bbbbbbbbbbbb")

    await db_session.execute(
        pg_insert(Vulnerability)
        .values(
            id=vuln_a_id,
            tenant_id=UUID(TENANT_A_ID),
            scan_id=scan_a_id,
            title="Alpha Vuln",
            severity="high",
            status="open",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(Vulnerability)
        .values(
            id=vuln_b_id,
            tenant_id=UUID(TENANT_B_ID),
            scan_id=scan_b_id,
            title="Beta Vuln",
            severity="medium",
            status="open",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()
    ids["vulnerabilities"]["tenant_a"] = vuln_a_id
    ids["vulnerabilities"]["tenant_b"] = vuln_b_id

    # --- Reports ---
    report_a_id = UUID("aaaaaaaa-3333-0000-0000-aaaaaaaaaaaa")
    report_b_id = UUID("bbbbbbbb-3333-0000-0000-bbbbbbbbbbbb")

    await db_session.execute(
        pg_insert(Report)
        .values(
            id=report_a_id,
            tenant_id=UUID(TENANT_A_ID),
            asset_id=asset_a_id,
            name="Alpha Report",
            report_type="vulnerability",
            status="completed",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(Report)
        .values(
            id=report_b_id,
            tenant_id=UUID(TENANT_B_ID),
            asset_id=asset_b_id,
            name="Beta Report",
            report_type="vulnerability",
            status="completed",
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()
    ids["reports"]["tenant_a"] = report_a_id
    ids["reports"]["tenant_b"] = report_b_id

    # --- Refresh Tokens ---
    rt_a_id = UUID("aaaaaaaa-4444-0000-0000-aaaaaaaaaaaa")
    rt_b_id = UUID("bbbbbbbb-4444-0000-0000-bbbbbbbbbbbb")

    from datetime import datetime, timezone, timedelta

    future = datetime.now(timezone.utc) + timedelta(days=7)

    await db_session.execute(
        pg_insert(RefreshToken)
        .values(
            id=rt_a_id,
            user_id=UUID(ADMIN_A_ID),
            token_hash="hash_alpha_refresh_token_for_testing",
            expires_at=future,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(RefreshToken)
        .values(
            id=rt_b_id,
            user_id=UUID(ADMIN_B_ID),
            token_hash="hash_beta_refresh_token_for_testing",
            expires_at=future,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()
    ids["refresh_tokens"]["tenant_a"] = rt_a_id
    ids["refresh_tokens"]["tenant_b"] = rt_b_id

    return ids
