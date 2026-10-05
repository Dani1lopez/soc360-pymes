"""Quota serialization and dispatch RLS using actual PostgreSQL commits."""

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, select, text, update

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.scans.service import (
    ScanQuotaExceededError,
    dispatch_scan,
)
from app.modules.tenants.models import Tenant


@pytest.fixture
async def committed_scans(isolated_db_session):
    tenant_id, asset_id = uuid4(), uuid4()
    scan_ids = [uuid4(), uuid4()]
    async with isolated_db_session() as db:
        await set_tenant_context(db, None, True)
        db.add(
            Tenant(
                id=tenant_id,
                name="Dispatch race",
                slug=f"dispatch-{tenant_id.hex}",
                scans_per_day=1,
            )
        )
        await db.flush()
        db.add(
            Asset(
                id=asset_id,
                tenant_id=tenant_id,
                asset_type="hostname",
                value=f"dispatch-{asset_id.hex}",
            )
        )
        await db.flush()
        for i, scan_id in enumerate(scan_ids):
            db.add(
                Scan(
                    id=scan_id,
                    tenant_id=tenant_id,
                    asset_id=asset_id,
                    name=f"dispatch-{i}",
                    scan_type="discovery",
                    status="pending",
                )
            )
        await db.commit()
    try:
        yield tenant_id, scan_ids
    finally:
        async with isolated_db_session() as db:
            await set_tenant_context(db, None, True)
            await db.execute(delete(Scan).where(Scan.tenant_id == tenant_id))
            await db.execute(delete(Asset).where(Asset.id == asset_id))
            await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await db.commit()


async def test_concurrent_daily_quota(isolated_db_session, committed_scans):
    """An in-flight dispatch blocks a second one until it commits.

    The interleaving is forced: without the tenant row lock, the second
    dispatch would not wait, would only see its own uncommitted row and would
    be accepted, exceeding ``scans_per_day=1``.
    """
    tenant_id, scan_ids = committed_scans
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    async with isolated_db_session() as holder, isolated_db_session() as contender:
        # Holder simulates a /run between its lock and its commit.
        await set_tenant_context(holder, tenant_id, False)
        await holder.execute(
            select(Tenant.id)
            .where(Tenant.id == tenant_id)
            .with_for_update(key_share=True)
        )
        await holder.execute(
            update(Scan)
            .where(Scan.id == scan_ids[0])
            .values(dispatched_at=datetime.now(timezone.utc))
        )

        engine = contender.bind.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            await set_tenant_context(contender, tenant_id, False)
            attempt = asyncio.create_task(
                dispatch_scan(scan_ids[1], tenant_id, contender)
            )
            await asyncio.sleep(0.5)
            assert not attempt.done(), "second dispatch must wait for the tenant lock"

            await holder.commit()
            with pytest.raises(ScanQuotaExceededError):
                await asyncio.wait_for(attempt, timeout=5)
        finally:
            event.remove(engine, "before_cursor_execute", capture)

    assert any("FOR NO KEY UPDATE" in sql for sql in statements)


async def test_dispatch_real_commit_rls(isolated_db_session, committed_scans):
    tenant_id, scan_ids = committed_scans
    async with isolated_db_session() as db:
        role = (
            await db.execute(
                text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
        await db.rollback()
        if role.rolsuper or role.rolbypassrls:
            pytest.skip("test database role bypasses RLS; cannot prove RLS dispatch")
        await set_tenant_context(db, tenant_id, False)
        scan = await dispatch_scan(scan_ids[0], tenant_id, db)
        # The service restores the transaction-local context after its commit.
        assert scan is not None and scan.dispatched_at is not None
        await db.commit()
        # A bare commit drops the context: RLS now hides the row.
        assert (
            await db.execute(select(Scan.id).where(Scan.id == scan_ids[0]))
        ).scalar_one_or_none() is None
        await set_tenant_context(db, tenant_id, False)
        assert (
            await db.execute(select(Scan.dispatched_at).where(Scan.id == scan_ids[0]))
        ).scalar_one() is not None
