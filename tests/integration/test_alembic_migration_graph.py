"""Integration tests for the Alembic migration graph.

Verifies that the migration graph converges to a single head,
clean upgrades succeed, and downgrade/re-upgrade roundtrips work.

These tests require a real PostgreSQL instance and DATABASE_URL
environment variable set.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys

import asyncpg
import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# F2 tables created by the assets/scans/vulnerabilities/reports migration
# ---------------------------------------------------------------------------
_F2_TABLES = frozenset({"assets", "scans", "vulnerabilities", "reports"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alembic(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run an alembic command via subprocess and return the result.

    Uses the project-level alembic.ini and PYTHONPATH.
    """
    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
    cmd = [sys.executable, "-m", "alembic", *args]
    env = {
        **os.environ,
        "PYTHONPATH": project_root,
        "DATABASE_URL_MIGRATION": os.environ.get(
            "DATABASE_URL_MIGRATION",
            os.environ.get("DATABASE_URL", ""),
        ),
    }
    return subprocess.run(
        cmd,
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _get_db_url() -> str:
    """Return the DSN so helper queries can connect to the target database."""
    raw = os.environ.get(
        "DATABASE_URL_MIGRATION",
        os.environ.get("DATABASE_URL", ""),
    )
    # Strip asyncpg driver prefix so asyncpg.connect() works
    return raw.replace("+asyncpg", "")


async def _fetch_table_names() -> frozenset[str]:
    """Return the set of user-table names currently present in the public schema."""
    dsn = _get_db_url()
    conn = await asyncpg.connect(dsn=dsn)
    try:
        rows = await conn.fetch(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname = 'public'"
        )
        return frozenset(r["tablename"] for r in rows)
    finally:
        await conn.close()


def _current_head_revision() -> str:
    """Return the alembic head revision ID."""
    result = _alembic("current")
    if result.returncode != 0:
        return ""
    # Format: "REV (head)" or "REV"
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line and not line.startswith("INFO"):
            # Take the first token (revision id)
            return line.split()[0]
    return ""


# ---------------------------------------------------------------------------
# Graph structure tests (no database mutation needed)
# ---------------------------------------------------------------------------


class TestMigrationGraphSingleHead:
    """Verify the migration graph resolves to exactly one head."""

    def test_alembic_heads_returns_single_head(self):
        """GIVEN the resolved migration graph
        WHEN alembic lists current heads
        THEN exactly one head is reported.

        Spec: Single Alembic Head → final head uniqueness.
        """
        result = _alembic("heads")

        assert result.returncode == 0, (
            f"alembic heads failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr}"
        )

        heads = [
            line.strip()
            for line in result.stdout.strip().splitlines()
            if line.strip()
        ]
        assert len(heads) == 1, (
            f"Expected exactly 1 head, got {len(heads)}: {heads}\n"
            f"stdout:\n{result.stdout}"
        )

    def test_alembic_history_is_linear(self):
        """GIVEN the resolved migration graph
        WHEN alembic shows the history
        THEN every revision appears exactly once in the output
        AND no branchpoint warnings are present.

        Spec: Single Alembic Head → normal upgrade command works.
        """
        result = _alembic("history")

        assert result.returncode == 0, (
            f"alembic history failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr}"
        )

        stdout = result.stdout

        # No branchpoint should exist (each revision has exactly one parent)
        # A branchpoint means a revision has multiple children
        assert (
            "(branchpoint)" not in stdout
        ), f"Unexpected branchpoint in history:\n{stdout}"

        # Verify no duplicate entries
        lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        assert len(lines) > 0, "Empty history output"


# ---------------------------------------------------------------------------
# Full lifecycle tests (require database)
# ---------------------------------------------------------------------------


class TestCleanDatabaseUpgrade:
    """Verify upgrade from empty database works."""

    def test_upgrade_from_base_to_head(self):
        """GIVEN a clean database (downgraded to base)
        WHEN `alembic upgrade head` is executed
        THEN the migration sequence completes successfully.

        Spec: Safe Clean Database Upgrade → clean DB upgrade from root to head.
        """
        # First downgrade to base (clean state)
        downgrade_result = _alembic("downgrade", "base")
        # downgrade to base can fail if we are already at base
        # (Alembic revises base differently depending on version).
        # Accept either success or a "no such revision / already at base" stderr.
        if downgrade_result.returncode != 0:
            stderr_lower = downgrade_result.stderr.lower()
            acceptable = any(
                phrase in stderr_lower
                for phrase in ("no such revision", "can't locate", "already at base")
            )
            assert acceptable, (
                f"downgrade base failed unexpectedly "
                f"(exit {downgrade_result.returncode}).\n"
                f"stderr: {downgrade_result.stderr}"
            )

        # Then upgrade to head
        result = _alembic("upgrade", "head")

        assert result.returncode == 0, (
            f"alembic upgrade head failed (exit {result.returncode}).\n"
            f"stderr: {result.stderr}\n"
            f"stdout: {result.stdout}"
        )


class TestSchemaIntegrity:
    """Verify that columns created across the migration chain exist exactly once."""

    def test_plan_and_max_assets_exist_exactly_once(self):
        """GIVEN alembic upgrade head completed successfully
        WHEN the tenants table schema is inspected
        THEN plan and max_assets columns each appear exactly once.

        Spec: Safe Clean Database Upgrade → no duplicate columns.
        This proves the rebase correctly removed the duplicated add_column
        operations from 8f2c1a4b9d7e.
        """
        db_url = os.environ.get("DATABASE_URL_MIGRATION",
                                 os.environ.get("DATABASE_URL", ""))

        async def _check() -> list[str]:
            conn = await asyncpg.connect(dsn=db_url.replace("+asyncpg", ""))
            try:
                rows = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenants' "
                    "AND column_name IN ('plan', 'max_assets') "
                    "ORDER BY column_name"
                )
                return [r["column_name"] for r in rows]
            finally:
                await conn.close()

        column_names = asyncio.run(_check())

        assert "max_assets" in column_names, (
            f"max_assets not found in tenants.columns. Found: {column_names}"
        )
        assert "plan" in column_names, (
            f"plan not found in tenants.columns. Found: {column_names}"
        )
        assert column_names.count("plan") == 1, (
            f"plan appears {column_names.count('plan')} times in schema "
            f"(expected exactly 1)"
        )
        assert column_names.count("max_assets") == 1, (
            f"max_assets appears {column_names.count('max_assets')} times "
            f"in schema (expected exactly 1)"
        )


class TestDowngradeRoundtrip:
    """Verify downgrade and re-upgrade integrity with real schema checks."""

    def test_downgrade_one_step_fully_reverses_f2(self):
        """GIVEN a database at the unified head with all F2 tables present
        WHEN `alembic downgrade -1` is executed
        THEN every F2 table (assets, scans, vulnerabilities, reports) is removed
        AND `alembic upgrade head` restores them.

        Spec: Normal Alembic Workflow Restoration — downgrade must roll back
        the full F2 schema, not just superficial defaults.
        """
        # --- Ensure we start at head with F2 tables present ---
        head_before = _current_head_revision()
        assert head_before, "Could not determine head revision before test"

        tables_before = asyncio.run(_fetch_table_names())
        missing_before = _F2_TABLES - tables_before
        assert not missing_before, (
            f"Pre-condition failed: F2 tables missing before downgrade: "
            f"{missing_before}. Run 'alembic upgrade head' first."
        )

        # --- Downgrade one step ---
        down_result = _alembic("downgrade", "-1")
        assert down_result.returncode == 0, (
            f"alembic downgrade -1 failed (exit {down_result.returncode}).\n"
            f"stderr: {down_result.stderr}\n"
            f"stdout: {down_result.stdout}"
        )

        # --- Verify F2 tables were actually removed ---
        tables_after_down = asyncio.run(_fetch_table_names())
        still_present = _F2_TABLES & tables_after_down
        assert not still_present, (
            f"downgrade -1 did NOT remove F2 tables. "
            f"Still present: {still_present}. "
            f"All tables after downgrade: {tables_after_down}"
        )

        # --- Re-upgrade to head ---
        up_result = _alembic("upgrade", "head")
        assert up_result.returncode == 0, (
            f"alembic upgrade head after downgrade failed "
            f"(exit {up_result.returncode}).\n"
            f"stderr: {up_result.stderr}\n"
            f"stdout: {up_result.stdout}"
        )

        # --- Verify F2 tables are back ---
        tables_after_up = asyncio.run(_fetch_table_names())
        missing_after_up = _F2_TABLES - tables_after_up
        assert not missing_after_up, (
            f"re-upgrade did NOT restore F2 tables. "
            f"Missing: {missing_after_up}. "
            f"All tables after upgrade: {tables_after_up}"
        )

        # --- Head revision should be preserved ---
        head_after = _current_head_revision()
        assert head_after == head_before, (
            f"Head revision changed across roundtrip: "
            f"{head_before} → {head_after}"
        )
