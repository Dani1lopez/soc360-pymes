"""Recover committed ready scans after a lost wake bell."""

import pytest
from sqlalchemy import select

from app.core.database import set_tenant_context
from app.modules.scans.models import Scan
from app.modules.scans.state import count_ready_scans
from app.worker import tasks
from tests.integration.test_scan_claim_next import queue_rows  # noqa: F401

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def enable_execution(monkeypatch):
    monkeypatch.setattr(tasks.settings, "SCAN_EXECUTION_ENABLED", True)


async def test_ready_count_and_cap(queue_rows, isolated_db_session):  # noqa: F811
    await queue_rows()
    await queue_rows()
    await queue_rows(dispatched=False)
    for status in ("running", "completed", "failed", "cancelled"):
        await queue_rows(status=status)
    async with isolated_db_session() as session:
        assert await count_ready_scans(session, limit=10) == 2
        assert not session.in_transaction()
        assert await count_ready_scans(session, limit=1) == 1
        for limit in (0, -1):
            with pytest.raises(ValueError):
                await count_ready_scans(session, limit=limit)


async def test_lost_bell_recovery(queue_rows, isolated_db_session, monkeypatch):  # noqa: F811
    scan_id, tenant_id = await queue_rows()
    bells = []
    monkeypatch.setattr(tasks.settings, "SCAN_EXECUTION_ENABLED", False)
    assert await tasks._wake() == "disabled"
    assert await tasks._pump(ring=lambda: bells.append(None)) == 0
    assert bells == []
    async with isolated_db_session() as session:
        await set_tenant_context(session, tenant_id)
        assert (
            await session.scalar(select(Scan.status).where(Scan.id == scan_id))
        ) == "pending"
    monkeypatch.setattr(tasks.settings, "SCAN_EXECUTION_ENABLED", True)
    assert await tasks._pump(ring=lambda: bells.append(None)) == 1
    assert len(bells) == 1

    async def execute(session, claimed_id, *, tenant_id, claimed):
        assert claimed_id == scan_id and claimed
        await set_tenant_context(session, tenant_id)
        assert (
            await session.scalar(select(Scan.status).where(Scan.id == scan_id))
        ) == "running"
        return "completed"

    assert await tasks._wake(execute=execute) == "completed"
    async with isolated_db_session() as session:
        await set_tenant_context(session, tenant_id)
        assert (
            await session.scalar(select(Scan.status).where(Scan.id == scan_id))
        ) == "running"
    assert await tasks._pump(ring=lambda: bells.append(None)) == 0
    assert len(bells) == 1
