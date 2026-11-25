"""H2-T2: the ownership declaration table, its forced RLS and its tenant-bound FK.

The declaration is what makes a scan legitimate (S5/S6), so the tenant boundary
is load-bearing: a row must be invisible to another tenant and the composite
foreign key must make a cross-tenant asset impossible to declare.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pytest

from app.core.database import set_tenant_context
from app.modules.assets.ownership.models import AssetOwnershipDeclaration
from tests.conftest import TENANT_A_ID, TENANT_B_ID

TABLE = "asset_ownership_declarations"
ASSET_A_ID = UUID("aaaaaaaa-2222-0000-0000-aaaaaaaaaaaa")
ASSET_B_ID = UUID("bbbbbbbb-2222-0000-0000-bbbbbbbbbbbb")


async def _seed_assets(db: AsyncSession) -> None:
    await set_tenant_context(db, None, is_superadmin=True)
    await db.execute(
        text(
            "INSERT INTO assets (id, tenant_id, value, asset_type, status) VALUES "
            "(:a, :ta, 'alpha.internal', 'hostname', 'active'), "
            "(:b, :tb, 'beta.internal', 'hostname', 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "a": ASSET_A_ID,
            "ta": UUID(TENANT_A_ID),
            "b": ASSET_B_ID,
            "tb": UUID(TENANT_B_ID),
        },
    )
    await db.flush()


async def test_the_table_exists_with_forced_rls_policy_and_grant(
    db_session: AsyncSession,
) -> None:
    await set_tenant_context(db_session, None, is_superadmin=True)
    row = (
        await db_session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :table"
            ),
            {"table": TABLE},
        )
    ).one_or_none()

    assert row is not None, f"{TABLE} does not exist"
    assert tuple(row) == (True, True), "RLS must be enabled and forced"

    policies = (
        (
            await db_session.execute(
                text("SELECT policyname FROM pg_policies WHERE tablename = :table"),
                {"table": TABLE},
            )
        )
        .scalars()
        .all()
    )
    assert policies == [f"rls_{TABLE}"]

    grants = (
        (
            await db_session.execute(
                text(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = :table AND grantee = 'soc360_app'"
                ),
                {"table": TABLE},
            )
        )
        .scalars()
        .all()
    )
    assert set(grants) == {"SELECT", "INSERT", "UPDATE", "DELETE"}


async def test_a_declaration_is_invisible_to_another_tenant(
    db_session: AsyncSession, seed_data
) -> None:
    await _seed_assets(db_session)
    await set_tenant_context(db_session, None, is_superadmin=True)
    db_session.add(
        AssetOwnershipDeclaration(
            tenant_id=UUID(TENANT_A_ID),
            asset_id=ASSET_A_ID,
            declared_value="alpha.internal",
            method="declaration",
            token="token-a",
            status="verified",
        )
    )
    await db_session.flush()

    await set_tenant_context(db_session, UUID(TENANT_B_ID), is_superadmin=False)
    visible = (
        await db_session.execute(
            select(func.count()).select_from(AssetOwnershipDeclaration)
        )
    ).scalar_one()
    assert visible == 0

    await set_tenant_context(db_session, UUID(TENANT_A_ID), is_superadmin=False)
    own = (
        await db_session.execute(
            select(func.count()).select_from(AssetOwnershipDeclaration)
        )
    ).scalar_one()
    assert own == 1


async def test_a_declaration_cannot_point_at_another_tenants_asset(
    db_session: AsyncSession, seed_data
) -> None:
    await _seed_assets(db_session)
    await set_tenant_context(db_session, None, is_superadmin=True)
    db_session.add(
        AssetOwnershipDeclaration(
            tenant_id=UUID(TENANT_A_ID),
            asset_id=ASSET_B_ID,
            declared_value="beta.internal",
            method="declaration",
            token="token-cross",
            status="pending",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.parametrize(
    "method,status",
    [("telepathy", "pending"), ("declaration", "telepathy")],
    ids=["bad-method", "bad-status"],
)
async def test_the_method_and_status_vocabulary_is_enforced(
    db_session: AsyncSession, seed_data, method: str, status: str
) -> None:
    await _seed_assets(db_session)
    await set_tenant_context(db_session, None, is_superadmin=True)
    db_session.add(
        AssetOwnershipDeclaration(
            tenant_id=UUID(TENANT_A_ID),
            asset_id=ASSET_A_ID,
            declared_value="alpha.internal",
            method=method,
            token="token-bad",
            status=status,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
