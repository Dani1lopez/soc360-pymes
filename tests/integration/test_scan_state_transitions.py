"""DB-backed tests for the atomic scan state machine — F2 slice 5, PR 5a.

Two test shapes:

- Savepoint tests use the standard ``db_session`` + ``seed_data`` fixtures
  and re-read plain COLUMN values from the cursor, so a stale identity-map
  object can never fake a pass.
- Race tests use ``isolated_db_session`` (pooled engine, real connections,
  real commits): two sessions really contend for the same row and the
  conditional UPDATE — not shared-session serialization — decides the winner.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.modules.assets.models import Asset
from app.modules.scans.models import Scan
from app.modules.scans.state import cancel_scan, transition_scan
from app.modules.tenants.models import Tenant
from tests.conftest import TENANT_A_ID

_SCAN_COLUMNS = (
    Scan.status,
    Scan.started_at,
    Scan.completed_at,
    Scan.failure_reason,
)


async def _enable_superadmin(session) -> None:
    await session.execute(text("SET LOCAL app.is_superadmin = 'true'"))


async def _seed_pending_scan(db_session, *, dispatched: bool = True) -> Scan:
    """Insert a fresh asset + pending scan in the savepoint transaction."""
    await _enable_superadmin(db_session)
    asset = Asset(
        id=uuid.uuid4(),
        tenant_id=UUID(TENANT_A_ID),
        value=f"state-machine-{uuid.uuid4().hex[:12]}",
        asset_type="hostname",
    )
    db_session.add(asset)
    await db_session.flush()
    scan = Scan(
        id=uuid.uuid4(),
        tenant_id=UUID(TENANT_A_ID),
        asset_id=asset.id,
        name=f"state-machine-{uuid.uuid4().hex[:12]}",
        scan_type="discovery",
        status="pending",
        # Omitted (not None) when undispatched so the column default applies.
        **({"dispatched_at": datetime.now(timezone.utc)} if dispatched else {}),
    )
    db_session.add(scan)
    await db_session.flush()
    return scan


async def _reread(db_session, scan_id: uuid.UUID):
    """Re-read raw column values from the cursor — bypasses the identity map."""
    result = await db_session.execute(select(*_SCAN_COLUMNS).where(Scan.id == scan_id))
    return result.one()


# ---------------------------------------------------------------------------
# Savepoint tests — timestamps and failure_reason persistence
# ---------------------------------------------------------------------------


async def test_undispatched_pending_cannot_run(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session, dispatched=False)

    assert await transition_scan(db_session, scan.id, to="running") is False

    row = await _reread(db_session, scan.id)
    assert row.status == "pending"
    assert row.started_at is None


async def test_undispatched_pending_can_cancel(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session, dispatched=False)

    assert await transition_scan(db_session, scan.id, to="cancelled") is True
    row = await _reread(db_session, scan.id)
    assert row.status == "cancelled"
    assert row.started_at is None


async def test_pending_to_running_sets_started_at(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session)

    assert await transition_scan(db_session, scan.id, to="running") is True

    row = await _reread(db_session, scan.id)
    assert row.status == "running"
    assert row.started_at is not None
    assert row.completed_at is None
    assert row.failure_reason is None


async def test_running_to_completed_sets_completed_at(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session)
    assert await transition_scan(db_session, scan.id, to="running") is True

    assert await transition_scan(db_session, scan.id, to="completed") is True

    row = await _reread(db_session, scan.id)
    assert row.status == "completed"
    assert row.started_at is not None
    assert row.completed_at is not None
    assert row.failure_reason is None


async def test_pending_dispatch_lost_fails_without_starting(
    db_session, seed_data
) -> None:
    scan = await _seed_pending_scan(db_session, dispatched=False)

    assert (
        await transition_scan(
            db_session, scan.id, to="failed", failure_reason="dispatch_lost"
        )
        is True
    )

    row = await _reread(db_session, scan.id)
    assert row.status == "failed"
    assert row.completed_at is not None
    assert row.started_at is None
    assert row.failure_reason == "dispatch_lost"
    assert (
        await transition_scan(
            db_session, scan.id, to="failed", failure_reason="dispatch_lost"
        )
        is False
    )


async def test_failed_stores_failure_reason(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session)
    assert await transition_scan(db_session, scan.id, to="running") is True

    assert (
        await transition_scan(
            db_session, scan.id, to="failed", failure_reason="timeout"
        )
        is True
    )

    row = await _reread(db_session, scan.id)
    assert row.status == "failed"
    assert row.failure_reason == "timeout"
    assert row.completed_at is not None


async def test_transition_from_terminal_returns_false_and_leaves_row_unchanged(
    db_session, seed_data
) -> None:
    scan = await _seed_pending_scan(db_session)
    assert await transition_scan(db_session, scan.id, to="running") is True
    assert await transition_scan(db_session, scan.id, to="completed") is True
    before = await _reread(db_session, scan.id)

    assert await transition_scan(db_session, scan.id, to="cancelled") is False
    assert (
        await transition_scan(
            db_session, scan.id, to="failed", failure_reason="timeout"
        )
        is False
    )

    after = await _reread(db_session, scan.id)
    assert (
        after.status,
        after.started_at,
        after.completed_at,
        after.failure_reason,
    ) == (
        before.status,
        before.started_at,
        before.completed_at,
        before.failure_reason,
    )


# ---------------------------------------------------------------------------
# Race tests — real connections, real commits
# ---------------------------------------------------------------------------


async def _seed_committed_scan(
    make_session, *, status: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Commit tenant + asset + scan through a real session; return (scan, asset)."""
    session = make_session()
    try:
        await _enable_superadmin(session)
        # Idempotent: the tenant may already be committed by a previous test.
        await session.execute(
            pg_insert(Tenant)
            .values(
                id=UUID(TENANT_A_ID),
                name="Empresa Alpha",
                slug="empresa-alpha",
                plan="starter",
                is_active=True,
                max_assets=50,
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        asset = Asset(
            id=uuid.uuid4(),
            tenant_id=UUID(TENANT_A_ID),
            value=f"state-race-{uuid.uuid4().hex[:12]}",
            asset_type="hostname",
        )
        session.add(asset)
        await session.flush()
        scan = Scan(
            id=uuid.uuid4(),
            tenant_id=UUID(TENANT_A_ID),
            asset_id=asset.id,
            name=f"state-race-{uuid.uuid4().hex[:12]}",
            scan_type="discovery",
            status=status,
            dispatched_at=datetime.now(timezone.utc),
            started_at=(datetime.now(timezone.utc) if status != "pending" else None),
        )
        session.add(scan)
        await session.flush()
        await session.commit()
        return scan.id, asset.id
    finally:
        await session.close()


async def _cleanup_committed_scan(
    make_session, scan_id: uuid.UUID, asset_id: uuid.UUID
) -> None:
    session = make_session()
    try:
        await _enable_superadmin(session)
        await session.execute(delete(Scan).where(Scan.id == scan_id))
        await session.execute(delete(Asset).where(Asset.id == asset_id))
        await session.commit()
    finally:
        await session.close()


async def test_concurrent_claims_pending_running_exactly_one_wins(
    isolated_db_session,
) -> None:
    scan_id, asset_id = await _seed_committed_scan(
        isolated_db_session, status="pending"
    )
    try:
        session_a = isolated_db_session()
        session_b = isolated_db_session()
        await _enable_superadmin(session_a)
        await _enable_superadmin(session_b)

        results = await asyncio.gather(
            transition_scan(session_a, scan_id, to="running"),
            transition_scan(session_b, scan_id, to="running"),
        )

        assert results.count(True) == 1, f"exactly one claim must win, got {results}"
        assert results.count(False) == 1, f"exactly one claim must lose, got {results}"

        reader = isolated_db_session()
        await _enable_superadmin(reader)
        row = (
            await reader.execute(select(*_SCAN_COLUMNS).where(Scan.id == scan_id))
        ).one()
        assert row.status == "running"
        assert row.started_at is not None
        await reader.close()
    finally:
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)


async def test_cancel_vs_complete_first_wins_other_returns_false(
    isolated_db_session,
) -> None:
    scan_id, asset_id = await _seed_committed_scan(
        isolated_db_session, status="running"
    )
    try:
        session_a = isolated_db_session()
        session_b = isolated_db_session()
        await _enable_superadmin(session_a)
        await _enable_superadmin(session_b)

        completed_first, cancelled_second = await asyncio.gather(
            transition_scan(session_a, scan_id, to="completed"),
            cancel_scan(session_b, scan_id),
        )

        assert sorted([completed_first, cancelled_second]) == [False, True], (
            "exactly one of complete/cancel must win, "
            f"got completed={completed_first} cancelled={cancelled_second}"
        )

        reader = isolated_db_session()
        await _enable_superadmin(reader)
        row = (
            await reader.execute(select(*_SCAN_COLUMNS).where(Scan.id == scan_id))
        ).one()
        expected = "completed" if completed_first else "cancelled"
        assert row.status == expected
        assert row.completed_at is not None
        await reader.close()
    finally:
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)
