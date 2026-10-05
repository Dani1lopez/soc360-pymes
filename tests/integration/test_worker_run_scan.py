"""Fresh worker loops complete a scan and skip duplicate delivery."""

import asyncio
import os
import sys
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select, update

from app.core.config import settings
from app.core.database import set_tenant_context
from app.modules.scans.executor import execute_scan
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunResult, run_nmap
from app.modules.scans.state import transition_scan
from app.modules.vulnerabilities.models import Vulnerability
from app.worker import tasks
from tests.conftest import TENANT_A_ID, TEST_DATABASE_URL
from tests.integration.test_scan_state_transitions import (
    _cleanup_committed_scan,
    _enable_superadmin,
    _seed_committed_scan,
)

pytestmark = pytest.mark.integration


async def test_undispatched_row_is_untouched(isolated_db_session):
    scan_id, asset_id = await _seed_committed_scan(
        isolated_db_session, status="pending"
    )
    try:
        async with isolated_db_session() as session:
            await _enable_superadmin(session)
            await session.execute(
                update(Scan).where(Scan.id == scan_id).values(dispatched_at=None)
            )
            await session.commit()
        assert await tasks._wake() == "idle"
        async with isolated_db_session() as session:
            await _enable_superadmin(session)
            row = (
                await session.execute(
                    select(Scan.status, Scan.started_at, Scan.dispatched_at).where(
                        Scan.id == scan_id
                    )
                )
            ).one()
            assert tuple(row) == ("pending", None, None)
    finally:
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)


async def test_worker_live_cancel(isolated_db_session, tmp_path):
    scan_id, asset_id = await _seed_committed_scan(
        isolated_db_session, status="pending"
    )
    tenant_id = UUID(TENANT_A_ID)
    pid_file = tmp_path / "nmap.pid"

    async def resolver(host):
        return ["93.184.216.34"]

    async def blocking_nmap(argv, **kwargs):
        # Write then rename: os.replace is atomic, so the test never observes
        # an existing but still empty pid file.
        tmp_file = f"{pid_file}.tmp"
        code = (
            "import os,time; from pathlib import Path; "
            f"Path({tmp_file!r}).write_text(str(os.getpid())); "
            f"os.replace({tmp_file!r}, {str(pid_file)!r}); time.sleep(60)"
        )
        return await run_nmap([sys.executable, "-c", code], **kwargs)

    running = asyncio.create_task(
        tasks._wake(
            execute=partial(execute_scan, resolver=resolver, run=blocking_nmap),
            cancel_poll_seconds=0.02,
        )
    )
    try:
        async with asyncio.timeout(5):
            while not pid_file.exists():
                if running.done():
                    pytest.fail(
                        f"executor stopped before process started: {running.result()}"
                    )
                await asyncio.sleep(0.01)
        pid = int(pid_file.read_text())
        async with isolated_db_session() as session:
            await set_tenant_context(session, tenant_id)
            assert await transition_scan(session, scan_id, to="cancelled")
        assert await asyncio.wait_for(asyncio.shield(running), 3) == "cancelled"
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        async with isolated_db_session() as session:
            await set_tenant_context(session, tenant_id)
            assert (
                await session.scalar(select(Scan.status).where(Scan.id == scan_id))
                == "cancelled"
            )
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)


async def test_worker_scan_duplicate_delivery(isolated_db_session, monkeypatch):
    assert TEST_DATABASE_URL == settings.DATABASE_URL
    scan_id, asset_id = await _seed_committed_scan(
        isolated_db_session, status="pending"
    )
    tenant_id = UUID(TENANT_A_ID)
    try:
        xml = (
            Path("tests/fixtures/nmap/normal.xml")
            .read_bytes()
            .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
        )

        async def fake_resolver(host: str) -> list[str]:
            return ["93.184.216.34"]

        runs = []

        async def fake_run(argv: list[str], **kwargs: object) -> NmapRunResult:
            runs.append(argv)
            return NmapRunResult(xml, "", 0)

        monkeypatch.setattr(
            tasks,
            "execute_scan",
            partial(execute_scan, resolver=fake_resolver, run=fake_run),
        )
        assert await tasks._wake() == "completed"
        assert await tasks._wake() == "idle"
        assert len(runs) == 1
        async with isolated_db_session() as session:
            await set_tenant_context(session, tenant_id)
            assert (
                await session.scalar(select(Scan.status).where(Scan.id == scan_id))
                == "completed"
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(Vulnerability)
                    .where(Vulnerability.scan_id == scan_id)
                )
                == 1
            )
    finally:
        async with isolated_db_session() as session:
            await _enable_superadmin(session)
            await session.execute(
                delete(Vulnerability).where(Vulnerability.scan_id == scan_id)
            )
            await session.commit()
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)
