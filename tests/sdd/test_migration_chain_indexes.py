"""Tests for migration chain index integrity.

Covers spec requirements:
  #9  Composite FK Child Indexes
  #10 Dropped User Indexes Restored
  #16 Migration Idempotency
  #17 Full Migration Chain Index State

TDD: RED phase — all tests must fail when indexes are missing.
"""

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_INDEXES = {
    "ix_vulnerabilities_scan_tenant",
    "ix_reports_asset_tenant",
    "ix_users_email_lower",
    "ix_users_tenant_active",
    "ix_scans_asset_tenant",
}


def _run_alembic(*args: str) -> str:
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def _existing_indexes() -> set[str]:
    """Return set of index names currently visible in pg_indexes."""
    import os
    import sys

    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault(
        "SECRET_KEY",
        "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
        "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
        "abcdefghijklmnopqrstuvwx",
    )

    from app.core.config import settings
    from sqlalchemy import text, make_url
    import asyncpg

    parsed = make_url(settings.DATABASE_URL_MIGRATION)
    import asyncio

    async def _fetch() -> set[str]:
        conn = await asyncpg.connect(
            user=parsed.username or "soc360_app",
            password=parsed.password or "",
            host=parsed.host or "localhost",
            port=parsed.port or 5432,
            database=parsed.database or "soc360_pymes_test",
        )
        try:
            rows = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
            )
            return {r["indexname"] for r in rows}
        finally:
            await conn.close()

    return asyncio.run(_fetch())


class TestIndexExistence:
    """RED: All tests expected to fail before migration."""

    def test_full_upgrade_yields_5_indexes(self):
        """Spec #17: Full upgrade yields 5 specific indexes."""
        indexes = _existing_indexes()
        missing = EXPECTED_INDEXES - indexes
        assert not missing, f"Missing indexes: {missing}"

    def test_round_trip_same_index_state(self):
        """Spec #16: Downgrade → re-upgrade yields identical index set."""
        # Capture state after a single upgrade
        _run_alembic("upgrade", "head")
        baseline = _existing_indexes()

        # Downgrade one step
        _run_alembic("downgrade", "-1")
        # Re-upgrade
        _run_alembic("upgrade", "head")
        after_roundtrip = _existing_indexes()

        assert baseline == after_roundtrip, (
            f"Round-trip index mismatch.\n"
            f"Baseline: {baseline}\n"
            f"After:    {after_roundtrip}"
        )

    def test_alembic_check_clean(self):
        """Spec #10: alembic check reports no pending differences."""
        _run_alembic("upgrade", "head")
        result = subprocess.run(
            ["uv", "run", "alembic", "check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        # alembic check returns exit code 0 when clean, 1 when dirty
        assert (
            result.returncode == 0
        ), f"alembic check reports pending differences:\n{result.stderr}"
