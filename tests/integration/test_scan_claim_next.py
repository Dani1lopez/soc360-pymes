"""Postgres queue claims with committed rows and forced lock interleaving."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from alembic.script import ScriptDirectory
from sqlalchemy import delete, func, select, text

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.scans.state import SCAN_TRANSITIONS, claim_next_scan
from app.modules.tenants.models import Tenant


@pytest_asyncio.fixture
async def queue_rows(isolated_db_session):
    make_session = isolated_db_session
    tenant_ids = []

    async def seed(*, status="pending", dispatched=True, age=0, tenant_id=None):
        async with make_session() as session:
            await set_tenant_context(session, None, is_superadmin=True)
            if tenant_id is None:
                tenant_id = uuid.uuid4()
                tenant_ids.append(tenant_id)
                session.add(
                    Tenant(
                        id=tenant_id,
                        name="Queue test",
                        slug=tenant_id.hex,
                        plan="starter",
                        is_active=True,
                        max_assets=50,
                    )
                )
                await session.flush()
            asset = Asset(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                value=f"queue-{uuid.uuid4().hex}",
                asset_type="hostname",
            )
            session.add(asset)
            await session.flush()
            scan = Scan(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                asset_id=asset.id,
                name=uuid.uuid4().hex,
                scan_type="discovery",
                status=status,
                dispatched_at=(
                    datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=age)
                    if dispatched
                    else None
                ),
            )
            session.add(scan)
            await session.commit()
            return scan.id, tenant_id

    try:
        yield seed
    finally:
        async with make_session() as session:
            await set_tenant_context(session, None, is_superadmin=True)
            # Tenant cascades remove every committed scan and asset from this fixture.
            await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))
            await session.commit()


async def test_fifo_and_database_clock(queue_rows, isolated_db_session):
    older = await queue_rows(age=0)
    newer = await queue_rows(age=1, tenant_id=older[1])
    assert "running" in SCAN_TRANSITIONS["pending"]
    async with isolated_db_session() as session:
        db_time = (await session.execute(select(func.now()))).scalar_one()
        assert await claim_next_scan(session) == older
        await set_tenant_context(session, None, is_superadmin=True)
        row = (
            await session.execute(
                select(Scan.status, Scan.started_at).where(Scan.id == older[0])
            )
        ).one()
        assert row.status == "running"
        assert row.started_at == db_time
        assert await claim_next_scan(session) == newer
        assert await claim_next_scan(session) is None


async def test_ignored_rows(queue_rows, isolated_db_session):
    await queue_rows(dispatched=False)
    for status in ("cancelled", "running", "completed", "failed"):
        await queue_rows(status=status)
    async with isolated_db_session() as session:
        assert await claim_next_scan(session) is None


async def test_cross_tenant(queue_rows, isolated_db_session):
    first = await queue_rows(age=0)
    second = await queue_rows(age=1)
    assert first[1] != second[1]
    async with isolated_db_session() as session:
        await set_tenant_context(session, first[1])
        assert await claim_next_scan(session) == first
        assert await claim_next_scan(session) == second


async def test_skip_locked_forced_interleaving(queue_rows, isolated_db_session):
    oldest = await queue_rows(age=0)
    second = await queue_rows(age=1)
    async with isolated_db_session() as holder:
        await set_tenant_context(holder, None, is_superadmin=True)
        await holder.execute(
            select(Scan.id).where(Scan.id == oldest[0]).with_for_update()
        )
        try:
            async with isolated_db_session() as contender:
                assert await asyncio.wait_for(claim_next_scan(contender), 3) == second
        finally:
            await holder.rollback()
    async with isolated_db_session() as session:
        assert await claim_next_scan(session) == oldest


def test_single_migration_head():
    assert len(ScriptDirectory("migrations").get_heads()) == 1


async def test_ready_index(db_session):
    index = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = 'scans' AND indexname = 'ix_scans_ready'"
            )
        )
    ).scalar_one()
    assert "(dispatched_at, id)" in index
    assert "WHERE" in index
    assert "status" in index and "'pending'" in index
    assert "dispatched_at IS NOT NULL" in index
    model_index = next(i for i in Scan.__table__.indexes if i.name == "ix_scans_ready")
    assert str(model_index.dialect_options["postgresql"]["where"]) == (
        "status = 'pending' AND dispatched_at IS NOT NULL"
    )
