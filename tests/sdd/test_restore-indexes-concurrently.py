"""Tests for the restore-indexes migration (issue #268).

Covers spec scenarios:
  migration-concurrent-index-build:
    SCN-1.1 Empty database upgrade creates all four indexes
    SCN-1.2 Populated database upgrade completes without raising
    SCN-2.1 Every CREATE INDEX CONCURRENTLY is wrapped by autocommit_block
    SCN-3.1 Healthy build flags (indisvalid AND indisready AND indislive)
    SCN-3.2 Invalid flag detection raises RuntimeError naming the index
    SCN-3.3 Offline --sql mode skips catalog validation
    SCN-5.1 Concurrent downgrade drops all four indexes
    SCN-6.1 Alembic history preserves revision chain

The migration lives at:
  migrations/versions/20260711_1700_restore_fk_child_and_user_indexes_a1b2c3d4e5f6.py

All tests run against the isolated PostgreSQL test database (soc360_test,
port 5434) provisioned by tests/conftest.py::prepare_database. The MIGRATION
role owns the catalog rows we mutate in SCN-3.2 — necessary for direct
pg_index mutations.

Strict TDD mode is inferred `false` (init cache did not expose strict_tdd: true).
If this project later enforces RED-before-GREEN via CI hooks, surface that in
the apply-progress risks rather than silently proceeding.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    ROOT
    / "migrations"
    / "versions"
    / "20260711_1700_restore_fk_child_and_user_indexes_a1b2c3d4e5f6.py"
)

# Reuse the conftest's _run_alembic to keep env wiring consistent.
from tests.conftest import (  # noqa: E402  (sys.path side-effect from conftest)
    MIGRATION_DATABASE_URL,
    _assert_safe_test_database,
    _run_alembic,
)

FOUR_INDEX_NAMES = frozenset(
    {
        "ix_vulnerabilities_scan_tenant",
        "ix_reports_asset_tenant",
        "ix_users_email_lower",
        "ix_users_tenant_active",
    }
)


# ---------------------------------------------------------------------------
# Helpers — direct DB access for catalog introspection / mutation
# ---------------------------------------------------------------------------


def _parse_migration_url() -> tuple[str, int, str, str, str]:
    """Return (user, port, host, password, database) from MIGRATION_DATABASE_URL."""
    from sqlalchemy import make_url

    parsed = make_url(MIGRATION_DATABASE_URL)
    user = parsed.username or "soc360_migration"
    port = parsed.port or 5432
    host = parsed.host or "localhost"
    password = parsed.password or ""
    database = parsed.database or "soc360_test"
    return user, port, host, password, database


def _sync_query(sql: str, *args: object) -> list[tuple]:
    """Run a single SQL statement synchronously via asyncpg.

    asyncpg's connection is async, but we wrap it in asyncio.run() to get a
    synchronous interface — sufficient for tests that need to inspect or
    mutate catalog state without holding an open event loop.
    """
    import asyncpg

    user, port, host, password, database = _parse_migration_url()

    async def _runner() -> list[tuple]:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        try:
            rows = await conn.fetch(sql, *args)
            return [tuple(r) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_runner())


def _sync_execute(sql: str, *args: object) -> None:
    """Run a non-returning SQL statement synchronously via asyncpg."""
    _sync_query(sql, *args)


def _list_target_indexes() -> dict[str, str]:
    """Return {indexname: indexdef} for the four target public indexes."""
    rows = _sync_query(
        "SELECT indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'public' AND indexname = ANY($1::text[])",
        list(FOUR_INDEX_NAMES),
    )
    return {r[0]: r[1] for r in rows}


def _index_health(indexname: str) -> tuple[bool, bool, bool]:
    """Return (indisvalid, indisready, indislive) for an index in public schema.

    Returns False-tuple if the index does not exist.
    """
    rows = _sync_query(
        """
        SELECT i.indisvalid, i.indisready, i.indislive
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = $1 AND n.nspname = 'public'
        """,
        indexname,
    )
    if not rows:
        return (False, False, False)
    return (bool(rows[0][0]), bool(rows[0][1]), bool(rows[0][2]))


def _set_index_validity(indexname: str, valid: bool) -> None:
    """Force indisvalid on a public index (test-only)."""
    _sync_execute(
        """
        UPDATE pg_index SET indisvalid = $1
        WHERE indexrelid = (
            SELECT c.oid FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relname = $2 AND n.nspname = 'public'
        )
        """,
        valid,
        indexname,
    )


def _load_migration_module():
    """Import the a1b2c3d4e5f6 migration module by file path."""
    spec = importlib.util.spec_from_file_location(
        "_restore_indexes_migration", MIGRATION_FILE
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load migration module at {MIGRATION_FILE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# SCN-1.1 — empty database upgrade creates all four indexes
# ---------------------------------------------------------------------------


def test_scn_1_1_empty_upgrade_creates_four_indexes() -> None:
    """Empty DB at c1d2e3f4a5b6 → upgrade head → all four target indexes exist."""
    _assert_safe_test_database()
    _run_alembic("downgrade", "c1d2e3f4a5b6")
    try:
        # Confirm the precondition: at the parent revision, none of the four exist.
        pre = _list_target_indexes()
        assert not (pre.keys() & FOUR_INDEX_NAMES), (
            f"Precondition failed: target indexes already exist: "
            f"{pre.keys() & FOUR_INDEX_NAMES}"
        )

        _run_alembic("upgrade", "head")

        post = _list_target_indexes()
        missing = FOUR_INDEX_NAMES - post.keys()
        assert not missing, (
            f"SCN-1.1 failed — missing indexes after upgrade: {missing}"
        )
    finally:
        # Always restore head state for the rest of the test session.
        _run_alembic("upgrade", "head")


# ---------------------------------------------------------------------------
# SCN-1.2 — populated database upgrade completes without raising
# ---------------------------------------------------------------------------


def test_scn_1_2_populated_upgrade_completes() -> None:
    """With rows in vulnerabilities / reports / users, upgrade head still succeeds."""
    _assert_safe_test_database()

    # Insert rows directly via asyncpg (no session transaction wrapper).
    # Use the migration URL because the migration role owns the catalog and
    # has INSERT privilege on the populated tables (RLS bypass via superuser
    # for this test-only DML).
    _sync_execute(
        "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
        "VALUES ('11111111-1111-1111-1111-111111111111', 'Alpha', 'alpha', "
        "'starter', true, 50) "
        "ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
        "VALUES ('22222222-2222-2222-2222-222222222222', 'Beta', 'beta', "
        "'free', true, 10) "
        "ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO users (id, tenant_id, email, hashed_password, full_name, "
        "role, is_active, is_superadmin) "
        "VALUES ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', NULL, "
        "'superadmin@soc360.test', 'fakehash', 'SA', 'superadmin', true, true) "
        "ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO users (id, tenant_id, email, hashed_password, full_name, "
        "role, is_active, is_superadmin) "
        "VALUES ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', "
        "'11111111-1111-1111-1111-111111111111', 'admin@alpha.test', "
        "'fakehash', 'AA', 'admin', true, false) "
        "ON CONFLICT (id) DO NOTHING"
    )

    # Insert at least one row in each F2 table to exercise the indexes.
    _sync_execute(
        "INSERT INTO assets (id, tenant_id, name, hostname, asset_type, status) "
        "VALUES ('aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa', "
        "'11111111-1111-1111-1111-111111111111', 'AlphaAsset', 'alpha-host', "
        "'host', 'active') ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO scans (id, tenant_id, asset_id, name, scan_type, status) "
        "VALUES ('aaaaaaaa-1111-0000-0000-aaaaaaaaaaaa', "
        "'11111111-1111-1111-1111-111111111111', "
        "'aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa', 'AlphaScan', "
        "'vulnerability', 'completed') ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO vulnerabilities (id, tenant_id, scan_id, title, severity, "
        "status) VALUES ('aaaaaaaa-2222-0000-0000-aaaaaaaaaaaa', "
        "'11111111-1111-1111-1111-111111111111', "
        "'aaaaaaaa-1111-0000-0000-aaaaaaaaaaaa', 'AlphaVuln', 'high', 'open') "
        "ON CONFLICT (id) DO NOTHING"
    )
    _sync_execute(
        "INSERT INTO reports (id, tenant_id, asset_id, name, report_type, "
        "status) VALUES ('aaaaaaaa-3333-0000-0000-aaaaaaaaaaaa', "
        "'11111111-1111-1111-1111-111111111111', "
        "'aaaaaaaa-0000-0000-0000-aaaaaaaaaaaa', 'AlphaReport', "
        "'vulnerability', 'completed') ON CONFLICT (id) DO NOTHING"
    )

    try:
        # The migration at head is idempotent: `upgrade head` against a DB
        # already at head is a no-op (CREATE INDEX IF NOT EXISTS would skip).
        # To force the upgrade to re-create the four indexes on populated
        # tables, downgrade first (drops the indexes via downgrade()), then
        # upgrade head (re-creates them).
        _run_alembic("downgrade", "c1d2e3f4a5b6")

        # Run upgrade head — this is the heart of SCN-1.2.
        _run_alembic("upgrade", "head")

        post = _list_target_indexes()
        missing = FOUR_INDEX_NAMES - post.keys()
        assert not missing, (
            f"SCN-1.2 failed — missing indexes after upgrade: {missing}"
        )
    finally:
        # Restore baseline state — run downgrade then upgrade to start fresh.
        _run_alembic("upgrade", "head")


# ---------------------------------------------------------------------------
# SCN-2.1 — every CREATE INDEX CONCURRENTLY is wrapped by autocommit_block
# ---------------------------------------------------------------------------


def test_scn_2_1_every_concurrent_create_is_in_autocommit_block() -> None:
    """Source-level check: every CREATE INDEX CONCURRENTLY is contained by
    its own `with op.get_context().autocommit_block():` block.
    """
    source = MIGRATION_FILE.read_text()

    # Strip strings and comments to focus on structural code.
    # A simpler approach: walk line-by-line and track with-block depth.
    # We rely on the discipline that the file uses `with op.get_context().autocommit_block():`
    # on its own line with consistent indentation.

    lines = source.splitlines()
    depth_at: dict[int, int] = {}  # line_no -> autocommit_block depth at this line
    current_depth = 0
    for lineno, line in enumerate(lines, start=1):
        # Detect enter/exit of autocommit_block
        if "autocommit_block" in line and "with" in line:
            current_depth += 1
        # Detect end of with block at the same indentation level — heuristic.
        # The actual code uses explicit dedent, but Python's parser knows.
        # For simplicity we count: each `with op.get_context().autocommit_block():`
        # is followed by exactly one statement at +1 indent, then dedent.
        depth_at[lineno] = current_depth
        # Crude exit detection: if line starts at module-level indent (0) and
        # `current_depth > 0`, we just decrement when we see dedented `op.execute`.
        # Better: track via indentation of `op.execute` inside a with-block.
        # Actually, the cleanest approach is to parse the structure via regex.

    # Reset and re-parse with regex for robust with-block detection.
    # Match `with op.get_context().autocommit_block():` followed by `op.execute(...)`
    pattern = re.compile(
        r"with\s+op\.get_context\(\)\.autocommit_block\(\):\s*\n"
        r"(\s+)op\.execute\(",
        re.MULTILINE,
    )
    autocommit_blocks = pattern.findall(source)
    # Each entry is the indentation of the `op.execute(` call. We need
    # exactly 4 autocommit statements: 4× CREATE + 4× DROP = 8.
    create_count = source.count("CREATE INDEX CONCURRENTLY")
    drop_count = source.count("DROP INDEX CONCURRENTLY")
    assert create_count == 4, (
        f"SCN-2.1 failed — expected 4 CREATE INDEX CONCURRENTLY statements, "
        f"found {create_count}"
    )
    assert drop_count == 4, (
        f"SCN-2.1 failed — expected 4 DROP INDEX CONCURRENTLY statements "
        f"in downgrade(), found {drop_count}"
    )
    assert len(autocommit_blocks) >= 8, (
        f"SCN-2.1 failed — expected at least 8 autocommit_block wrappers "
        f"(4 upgrade + 4 downgrade), found {len(autocommit_blocks)}"
    )


# ---------------------------------------------------------------------------
# SCN-3.1 — healthy build flags (indisvalid AND indisready AND indislive)
# ---------------------------------------------------------------------------


def test_scn_3_1_healthy_build_flags() -> None:
    """After upgrade head, every target index has all three flags true."""
    _assert_safe_test_database()
    _run_alembic("upgrade", "head")
    for name in FOUR_INDEX_NAMES:
        valid, ready, live = _index_health(name)
        assert valid and ready and live, (
            f"SCN-3.1 failed — index {name!r} unhealthy: "
            f"indisvalid={valid}, indisready={ready}, indislive={live}"
        )


# ---------------------------------------------------------------------------
# SCN-3.2 — invalid flag detection raises RuntimeError naming the index
# ---------------------------------------------------------------------------


def test_scn_3_2_invalid_flag_detection() -> None:
    """After UPDATE pg_index SET indisvalid=false, _assert_index_health raises."""
    _assert_safe_test_database()
    _run_alembic("upgrade", "head")
    target = "ix_vulnerabilities_scan_tenant"

    # Force the index into an invalid state.
    _set_index_validity(target, False)
    try:
        # Load the migration module and invoke the helper directly.
        mod = _load_migration_module()

        # The helper is `_assert_index_health(name)` — Task 2 adds this.
        # Before Task 2 the attribute does not exist; the test fails RED.
        assert hasattr(mod, "_assert_index_health"), (
            "SCN-3.2 pre-Task-2 RED: migration module has no "
            "_assert_index_health helper yet"
        )

        # Invoke via a real Alembic MigrationContext so `op.get_bind()`
        # returns a working sync connection.
        from sqlalchemy.ext.asyncio import create_async_engine
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext

        async def _run() -> None:
            engine = create_async_engine(MIGRATION_DATABASE_URL)
            async with engine.connect() as conn:
                def _call(sync_conn: object) -> None:
                    ctx = MigrationContext.configure(sync_conn)
                    mod.op = Operations(ctx)
                    mod._assert_index_health(target)  # type: ignore[attr-defined]

                await conn.run_sync(_call)
            await engine.dispose()

        with pytest.raises(RuntimeError, match=r"indisvalid") as exc_info:
            asyncio.run(_run())
        # The error message must name the offending index.
        assert target in str(exc_info.value), (
            f"SCN-3.2 failed — RuntimeError must name {target!r}: "
            f"{exc_info.value!r}"
        )
    finally:
        # Restore the flag — leave the DB healthy for other tests.
        _set_index_validity(target, True)


# ---------------------------------------------------------------------------
# SCN-3.3 — offline --sql mode skips catalog validation
# ---------------------------------------------------------------------------


def test_scn_3_3_offline_sql_skips_catalog_validation() -> None:
    """`alembic upgrade --sql` emits 4 CREATE INDEX CONCURRENTLY statements
    and no SELECT indexdef / pg_index query.
    """
    _assert_safe_test_database()
    out_file = ROOT / "tests" / "sdd" / "_offline_sql.out"
    if out_file.exists():
        out_file.unlink()
    try:
        # Run `alembic upgrade --sql` with stdout redirected to file. The
        # conftest's _run_alembic captures stdout, so use subprocess directly
        # here with shell redirection for the SQL output.
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head", "--sql"],
            cwd=ROOT,
            env={
                **os.environ,
                "DATABASE_URL_MIGRATION": MIGRATION_DATABASE_URL,
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"`alembic upgrade --sql` failed: {result.stderr}"
        )
        sql_text = result.stdout

        create_count = sql_text.count("CREATE INDEX CONCURRENTLY")
        assert create_count == 4, (
            f"SCN-3.3 failed — expected 4 CREATE INDEX CONCURRENTLY in "
            f"offline SQL, found {create_count}"
        )

        # The validation queries (SELECT indexdef FROM pg_indexes, the
        # pg_index indisvalid/indisready/indislive triple) must NOT appear
        # in offline SQL — the migration skips catalog reads when offline.
        low = sql_text.lower()
        assert "select indexdef" not in low, (
            "SCN-3.3 failed — offline SQL contains `SELECT indexdef` "
            "(catalog validation must be skipped in --sql mode)"
        )
        assert "pg_index" not in low, (
            "SCN-3.3 failed — offline SQL references pg_index "
            "(catalog validation must be skipped in --sql mode)"
        )
    finally:
        if out_file.exists():
            out_file.unlink()


# ---------------------------------------------------------------------------
# SCN-5.1 — concurrent downgrade drops all four indexes
# ---------------------------------------------------------------------------


def test_scn_5_1_concurrent_downgrade_drops_all_four() -> None:
    """`alembic downgrade -1` removes the four indexes (DROP CONCURRENTLY)."""
    _assert_safe_test_database()
    _run_alembic("upgrade", "head")
    # Sanity: confirm all four exist before the downgrade.
    pre = _list_target_indexes()
    assert FOUR_INDEX_NAMES.issubset(pre.keys()), (
        f"Precondition failed — missing before downgrade: "
        f"{FOUR_INDEX_NAMES - pre.keys()}"
    )

    _run_alembic("downgrade", "-1")

    post = _list_target_indexes()
    leftover = FOUR_INDEX_NAMES & post.keys()
    assert not leftover, (
        f"SCN-5.1 failed — indexes still present after downgrade: {leftover}"
    )

    # Restore head for the rest of the session.
    _run_alembic("upgrade", "head")


# ---------------------------------------------------------------------------
# SCN-6.1 — alembic history preserves revision chain
# ---------------------------------------------------------------------------


def test_scn_6_1_revision_chain_preserved() -> None:
    """`alembic history` shows both a1b2c3d4e5f6 and c1d2e3f4a5b6 with no
    extra node inserted before the legacy parent.
    """
    _assert_safe_test_database()
    result = subprocess.run(
        ["uv", "run", "alembic", "history"],
        cwd=ROOT,
        env={
            **os.environ,
            "DATABASE_URL_MIGRATION": MIGRATION_DATABASE_URL,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"`alembic history` failed: {result.stderr}"
    )
    history = result.stdout

    assert "a1b2c3d4e5f6" in history, (
        "SCN-6.1 failed — revision `a1b2c3d4e5f6` missing from history"
    )
    assert "c1d2e3f4a5b6" in history, (
        "SCN-6.1 failed — revision `c1d2e3f4a5b6` missing from history"
    )

    # Verify the parent chain in the migration file itself.
    source = MIGRATION_FILE.read_text()
    assert 'revision: str = "a1b2c3d4e5f6"' in source, (
        "SCN-6.1 failed — migration source has wrong revision_id"
    )
    assert 'down_revision: Union[str, None] = "c1d2e3f4a5b6"' in source, (
        "SCN-6.1 failed — migration source has wrong down_revision"
    )
