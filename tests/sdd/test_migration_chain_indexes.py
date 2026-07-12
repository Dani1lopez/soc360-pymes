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

# Expected substrings (lower-cased) required in each pg_indexes.indexdef.
# `CREATE INDEX IF NOT EXISTS` only matches the NAME; a same-named index with
# wrong columns or a wrong expression would be silently accepted, so we
# re-read pg_indexes.indexdef and validate the table + ordered columns or
# the expression.
EXPECTED_INDEX_DEFS: dict[str, list] = {
    "ix_vulnerabilities_scan_tenant": [
        "on public.vulnerabilities",
        "(scan_id, tenant_id)",
    ],
    "ix_reports_asset_tenant": [
        "on public.reports",
        "(asset_id, tenant_id)",
    ],
    "ix_users_email_lower": [
        "on public.users",
        # Postgres renders `lower(email)` as `lower((email)::text)`; the
        # substring must reflect that exact rendering.
        "lower((email)",
    ],
    "ix_users_tenant_active": [
        "on public.users",
        "(tenant_id, is_active)",
    ],
    "ix_scans_asset_tenant": [
        "on public.scans",
        "(asset_id, tenant_id)",
    ],
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


def _existing_indexes() -> dict[str, str]:
    """Return {indexname: indexdef} for every index currently in pg_indexes."""
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

    async def _fetch() -> dict[str, str]:
        conn = await asyncpg.connect(
            user=parsed.username or "soc360_app",
            password=parsed.password or "",
            host=parsed.host or "localhost",
            port=parsed.port or 5432,
            database=parsed.database or "soc360_pymes_test",
        )
        try:
            rows = await conn.fetch(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public'"
            )
            return {r["indexname"]: r["indexdef"] for r in rows}
        finally:
            await conn.close()

    return asyncio.run(_fetch())


def _assert_indexes_have_expected_definitions(indexes: dict[str, str]) -> None:
    """Validate that each expected index has the required definition tokens.

    Catches same-named indexes with wrong columns/expression that
    ``CREATE INDEX IF NOT EXISTS`` would silently accept.
    """
    missing = EXPECTED_INDEXES - indexes.keys()
    assert not missing, f"Missing indexes: {missing}"
    for name, required in EXPECTED_INDEX_DEFS.items():
        indexdef = indexes[name]
        low = indexdef.lower()
        for token in required:
            assert token in low, (
                f"index {name!r} definition missing token {token!r}: {indexdef}"
            )


class TestIndexExistence:
    """RED: All tests expected to fail before migration."""

    def test_full_upgrade_yields_5_indexes(self):
        """Spec #17: Full upgrade yields 5 specific indexes (by name)."""
        indexes = _existing_indexes()
        missing = EXPECTED_INDEXES - indexes.keys()
        assert not missing, f"Missing indexes: {missing}"

    def test_indexes_have_expected_definitions(self):
        """Each expected index's pg_indexes.indexdef matches the spec.

        Same-named indexes with wrong columns/expression are silently kept by
        ``CREATE INDEX IF NOT EXISTS``; we re-read ``pg_indexes.indexdef`` to
        fail loudly on definition drift.
        """
        indexes = _existing_indexes()
        _assert_indexes_have_expected_definitions(indexes)

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

        assert baseline.keys() == after_roundtrip.keys(), (
            f"Round-trip index set mismatch.\n"
            f"Baseline: {sorted(baseline)}\n"
            f"After:    {sorted(after_roundtrip)}"
        )
        # Validate definitions too — definitions must round-trip identically.
        _assert_indexes_have_expected_definitions(after_roundtrip)

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
