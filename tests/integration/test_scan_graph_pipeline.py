"""Slice 9 T5: the executor runs the scan graph end to end.

The executor keeps the state machine; the graph does the work. These tests pin
the seam that only exists once both are wired: a finding that one scan observes
twice is stored once, and the scan still completes with the raw Nmap output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.assets.ownership.models import AssetOwnershipDeclaration
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
    # H2-T5: the executor requires a verified ownership declaration.
    declared_value = await db_session.scalar(
        select(Asset.value).where(Asset.id == scan.asset_id)
    )
    db_session.add(
        AssetOwnershipDeclaration(
            tenant_id=scan.tenant_id,
            asset_id=scan.asset_id,
            declared_value=declared_value,
            method="declaration",
            token="graph-pipeline",
            status="verified",
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()
    await db_session.commit()

    async def resolver(host: str) -> list[str]:
        return ["10.0.0.7", "fd00::1"]

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
