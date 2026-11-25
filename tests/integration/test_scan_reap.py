"""Database-clock reconciliation of lost worker claims."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.database import set_tenant_context
from app.modules.scans.models import Scan
from app.modules.scans.state import claim_next_scan, reap_stale_scans
from app.worker.celery_app import STALE_SCAN_SECONDS
from tests.integration.test_scan_claim_next import queue_rows  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("stale", [True, False])
async def test_lost_claim(queue_rows, isolated_db_session, stale):  # noqa: F811
    scan_id, _ = await queue_rows()
    async with isolated_db_session() as session:
        assert (await claim_next_scan(session))[0] == scan_id
        if stale:
            await set_tenant_context(session, None, is_superadmin=True)
            await session.execute(
                update(Scan)
                .where(Scan.id == scan_id)
                .values(
                    started_at=func.now() - timedelta(seconds=STALE_SCAN_SECONDS + 1)
                )
            )
            await session.commit()
        count = await reap_stale_scans(session, older_than_seconds=STALE_SCAN_SECONDS)
        assert count == int(stale)
        await set_tenant_context(session, None, is_superadmin=True)
        row = (
            await session.execute(
                select(Scan.status, Scan.failure_reason, Scan.completed_at).where(
                    Scan.id == scan_id
                )
            )
        ).one()
        assert row.status == ("failed" if stale else "running")
        assert row.failure_reason == ("worker_lost" if stale else None)
        assert (row.completed_at is not None) == stale


async def test_other_statuses_untouched(queue_rows, isolated_db_session):  # noqa: F811
    ids = [(await queue_rows(status=status))[0] for status in ("pending", "completed")]
    async with isolated_db_session() as session:
        await set_tenant_context(session, None, is_superadmin=True)
        await session.execute(
            update(Scan)
            .where(Scan.id.in_(ids))
            .values(started_at=func.now() - timedelta(seconds=STALE_SCAN_SECONDS + 1))
        )
        await session.commit()
        assert (
            await reap_stale_scans(session, older_than_seconds=STALE_SCAN_SECONDS) == 0
        )
        await set_tenant_context(session, None, is_superadmin=True)
        statuses = await session.scalars(select(Scan.status).where(Scan.id.in_(ids)))
        assert set(statuses.all()) == {"pending", "completed"}


@pytest.mark.parametrize("seconds", [0, -1])
async def test_invalid_duration(isolated_db_session, seconds):
    async with isolated_db_session() as session:
        with pytest.raises(ValueError):
            await reap_stale_scans(session, older_than_seconds=seconds)
