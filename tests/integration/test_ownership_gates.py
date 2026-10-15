"""H2-T5: the executor gate, the only code that runs on every claim.

A declaration revoked after the scan was queued must still block execution, and
a missing declaration must never reach Nmap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import set_tenant_context
from app.modules.assets.ownership.gate import NOT_VERIFIED_REASON
from app.modules.assets.ownership.models import AssetOwnershipDeclaration
from app.modules.scans.executor import execute_scan
from app.modules.scans.models import Scan
from app.modules.scans.nmap.runner import NmapRunResult
from app.modules.scans.state import claim_next_scan
from tests.integration.test_scan_state_transitions import _seed_pending_scan

XML = (
    Path("tests/fixtures/nmap/normal.xml")
    .read_bytes()
    .replace(b"unsafe &lt;script&gt; &amp; data", b"VULNERABLE CVSS: 7.5")
)


async def _declare(db, scan: Scan, *, status: str) -> None:
    db.add(
        AssetOwnershipDeclaration(
            tenant_id=scan.tenant_id,
            asset_id=scan.asset_id,
            method="declaration",
            token="executor-gate",
            status=status,
            verified_at=datetime.now(timezone.utc) if status == "verified" else None,
        )
    )
    await db.flush()


async def _row(db, scan_id) -> tuple:
    await set_tenant_context(db, None, is_superadmin=True)
    return (
        await db.execute(
            select(Scan.status, Scan.failure_reason, Scan.raw_output).where(
                Scan.id == scan_id
            )
        )
    ).one()


@pytest.mark.parametrize("declaration", ["missing", "pending", "revoked", "failed"])
async def test_a_scan_without_a_verified_declaration_never_reaches_nmap(
    db_session, seed_data, declaration: str
) -> None:
    scan = await _seed_pending_scan(db_session)
    if declaration != "missing":
        await _declare(db_session, scan, status=declaration)
    await db_session.commit()

    async def resolver(host: str) -> list[str]:
        return ["10.0.0.7"]

    async def run(argv, **kwargs):
        pytest.fail("Nmap must not run without a verified declaration")

    claimed = await claim_next_scan(db_session)
    assert claimed is not None
    scan_id, tenant_id = claimed

    result = await execute_scan(
        db_session,
        scan_id,
        tenant_id=tenant_id,
        claimed=True,
        resolver=resolver,
        run=run,
    )

    assert result == "failed"
    status, failure_reason, raw_output = await _row(db_session, scan_id)
    assert status == "failed"
    assert failure_reason == NOT_VERIFIED_REASON
    assert raw_output is None


async def test_a_verified_declaration_lets_the_claimed_scan_run(
    db_session, seed_data
) -> None:
    scan = await _seed_pending_scan(db_session)
    await _declare(db_session, scan, status="verified")
    await db_session.commit()

    calls: list = []

    async def resolver(host: str) -> list[str]:
        return ["10.0.0.7"]

    async def run(argv, **kwargs):
        calls.append(argv)
        return NmapRunResult(XML, "", 0)

    claimed = await claim_next_scan(db_session)
    assert claimed is not None
    scan_id, tenant_id = claimed

    result = await execute_scan(
        db_session,
        scan_id,
        tenant_id=tenant_id,
        claimed=True,
        resolver=resolver,
        run=run,
    )

    assert result == "completed"
    assert len(calls) == 1
    status, failure_reason, raw_output = await _row(db_session, scan_id)
    assert status == "completed"
    assert failure_reason is None
    assert raw_output
