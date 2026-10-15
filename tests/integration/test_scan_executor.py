"""DB executor contracts; require the PostgreSQL integration fixtures."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import set_tenant_context
from app.modules.assets.ownership.models import AssetOwnershipDeclaration
from app.modules.scans.executor import execute_scan
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunError, NmapRunResult
from app.modules.scans.state import cancel_scan
from app.modules.vulnerabilities.models import Vulnerability
from tests.integration.test_scan_state_transitions import _seed_pending_scan

XML = (
    Path("tests/fixtures/nmap/normal.xml")
    .read_bytes()
    .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
)


async def _declare_verified(db_session, scan) -> None:
    """H2-T5: execute_scan requires a verified ownership declaration."""
    db_session.add(
        AssetOwnershipDeclaration(
            tenant_id=scan.tenant_id,
            asset_id=scan.asset_id,
            method="declaration",
            token="executor-test",
            status="verified",
            verified_at=datetime.now(timezone.utc),
        )
    )
    await db_session.flush()


async def test_executor_skips_undispatched_scan(db_session, seed_data):
    scan = await _seed_pending_scan(db_session, dispatched=False)
    scan_id, tenant_id = scan.id, scan.tenant_id
    await db_session.commit()
    calls = []

    async def resolver(host):
        return ["10.0.0.7"]

    async def run(argv, **kwargs):
        calls.append(argv)
        return NmapRunResult(XML, "", 0)

    assert (
        await execute_scan(
            db_session, scan_id, tenant_id=tenant_id, resolver=resolver, run=run
        )
        == "skipped"
    )
    assert calls == []
    await set_tenant_context(db_session, tenant_id)
    assert (
        await db_session.scalar(select(Scan.status).where(Scan.id == scan_id))
        == "pending"
    )


@pytest.mark.parametrize("mode", ["completed", "cancelled", "failed"])
async def test_executor_persistence(db_session, seed_data, mode):
    scan = await _seed_pending_scan(db_session)
    scan_id, tenant_id = scan.id, scan.tenant_id
    await _declare_verified(db_session, scan)
    # Commit the seed so executor rollback cannot remove it.
    await db_session.commit()

    async def resolver(host):
        return ["192.168.1.7"]

    async def run(argv, **kwargs):
        if mode == "failed":
            raise NmapRunError("timeout", "not persisted")
        if mode == "cancelled":
            await set_tenant_context(db_session, tenant_id)
            assert await cancel_scan(db_session, scan_id)
        return NmapRunResult(XML, "", 0)

    assert (
        await execute_scan(
            db_session, scan_id, tenant_id=tenant_id, resolver=resolver, run=run
        )
        == mode
    )
    await set_tenant_context(db_session, tenant_id)
    row = (
        await db_session.execute(
            select(Scan.status, Scan.raw_output, Scan.failure_reason).where(
                Scan.id == scan_id
            )
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
    assert row.status == mode
    if mode == "completed":
        assert row.raw_output == XML.decode()
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].tenant_id == tenant_id
    else:
        assert row.raw_output is None
        assert findings == []
    assert row.failure_reason == ("timeout" if mode == "failed" else None)
