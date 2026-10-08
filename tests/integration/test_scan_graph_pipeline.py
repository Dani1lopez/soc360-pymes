"""Slice 9 T5: the executor runs the scan graph end to end.

The executor keeps the state machine; the graph does the work. These tests pin
the seam that only exists once both are wired: a finding that one scan observes
twice is stored once, and the scan still completes with the raw Nmap output.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import set_tenant_context
from app.modules.scans.executor import execute_scan
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunResult
from app.modules.vulnerabilities.models import Vulnerability
from tests.integration.test_scan_state_transitions import _seed_pending_scan

pytestmark = pytest.mark.integration

XML = (
    Path("tests/fixtures/nmap/normal.xml")
    .read_bytes()
    .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
)


async def test_a_finding_observed_twice_is_stored_once(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session)
    scan_id, tenant_id = scan.id, scan.tenant_id
    await db_session.commit()

    async def resolver(host: str) -> list[str]:
        return ["93.184.216.34", "2606:4700:4700::1111"]

    async def run(argv, **kwargs):
        # Both address families report the same script on the same surface.
        return NmapRunResult(XML, "", 0)

    assert (
        await execute_scan(
            db_session, scan_id, tenant_id=tenant_id, resolver=resolver, run=run
        )
        == "completed"
    )

    await set_tenant_context(db_session, tenant_id)
    row = (
        await db_session.execute(
            select(Scan.status, Scan.raw_output).where(Scan.id == scan_id)
        )
    ).one()
    findings = (
        (
            await db_session.execute(
                select(Vulnerability).where(Vulnerability.scan_id == scan_id)
            )
        )
        .scalars()
        .all()
    )
    assert row.status == "completed"
    assert row.raw_output == XML.decode() + "\n" + XML.decode()
    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].vulnerability_metadata["source"] == "nmap"
