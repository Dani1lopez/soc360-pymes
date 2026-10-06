"""DB-backed coverage for the dispatch timestamp and quota/reaper index."""

from datetime import datetime, timedelta, timezone

from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from app.modules.scans.models import Scan
from tests.integration.test_scan_state_transitions import _seed_pending_scan


def test_migration_chain_has_single_head() -> None:
    assert len(ScriptDirectory("migrations").get_heads()) == 1


async def test_dispatched_at_defaults_to_null(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session, dispatched=False)
    result = await db_session.execute(
        select(Scan.dispatched_at).where(Scan.id == scan.id)
    )
    assert result.scalar_one() is None


async def test_dispatched_at_round_trips_aware_datetime(db_session, seed_data) -> None:
    scan = await _seed_pending_scan(db_session)
    dispatched_at = datetime(2026, 10, 2, 12, 30, tzinfo=timezone(timedelta(hours=2)))
    scan.dispatched_at = dispatched_at
    await db_session.flush()
    result = await db_session.execute(
        select(Scan.dispatched_at).where(Scan.id == scan.id)
    )
    stored = result.scalar_one()
    assert stored == dispatched_at
    assert stored.utcoffset() is not None


async def test_dispatch_column_and_index_exist(db_session) -> None:
    column = (
        await db_session.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'scans' "
                "AND column_name = 'dispatched_at'"
            )
        )
    ).one()
    assert column.data_type == "timestamp with time zone"
    assert column.is_nullable == "YES"
    index = (
        await db_session.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' "
                "AND tablename = 'scans' "
                "AND indexname = 'ix_scans_tenant_dispatched_at'"
            )
        )
    ).scalar_one()
    assert "(tenant_id, dispatched_at)" in index
    assert "UNIQUE" not in index
    assert "WHERE" not in index
