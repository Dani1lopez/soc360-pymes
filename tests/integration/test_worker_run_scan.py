"""Fresh worker loops complete a scan and skip duplicate delivery."""

import asyncio
from functools import partial
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import set_tenant_context
from app.modules.scans.executor import execute_scan
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunResult
from app.modules.vulnerabilities.models import Vulnerability
from app.worker import tasks
from tests.conftest import TENANT_A_ID, TEST_DATABASE_URL
from tests.integration.test_scan_state_transitions import (
    _cleanup_committed_scan,
    _enable_superadmin,
    _seed_committed_scan,
)

pytestmark = pytest.mark.integration


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

        async def fake_run(argv: list[str], **kwargs: object) -> NmapRunResult:
            return NmapRunResult(xml, "", 0)

        monkeypatch.setattr(
            tasks,
            "execute_scan",
            partial(execute_scan, resolver=fake_resolver, run=fake_run),
        )
        assert (
            await asyncio.to_thread(tasks.run_scan.run, str(scan_id), str(tenant_id))
            == "completed"
        )
        assert (
            await asyncio.to_thread(tasks.run_scan.run, str(scan_id), str(tenant_id))
            == "skipped"
        )
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
