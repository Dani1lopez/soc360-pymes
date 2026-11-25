from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest
from sqlalchemy.engine import URL


@pytest.fixture(scope="module")
def migration_sql() -> str:
    """Generate the offline SQL for the full migration chain up to HEAD.

    This is a DB-free assertion: Alembic renders SQL without connecting to
    PostgreSQL, so it proves the migration scripts contain the expected
    composite foreign keys and parent unique constraints.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = {
        **os.environ,
        "PYTHONPATH": project_root,
        # Inherit DATABASE_URL_MIGRATION from the test environment; root
        # conftest provides a default if none is set.
    }

    # Ensure the variable is present so env.py can render SQL literal binds.
    if "DATABASE_URL_MIGRATION" not in env:
        env["DATABASE_URL_MIGRATION"] = str(
            URL.create(
                "postgresql+asyncpg",
                username="test",
                password="test",
                host="localhost",
                port=5433,
                database="soc360_test",
            )
        )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic offline SQL generation failed (exit {result.returncode}):\n"
            f"{result.stderr}"
        )

    return result.stdout.lower()


@pytest.fixture(scope="module")
def migration_downgrade_sql() -> str:
    """Generate the offline SQL for downgrading the last revision (c1d2e3f4a5b6 → bfca7016cbb7).

    This proves the downgrade restores the original simple FK and index.
    """
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = {
        **os.environ,
        "PYTHONPATH": project_root,
    }

    if "DATABASE_URL_MIGRATION" not in env:
        env["DATABASE_URL_MIGRATION"] = str(
            URL.create(
                "postgresql+asyncpg",
                username="test",
                password="test",
                host="localhost",
                port=5433,
                database="soc360_test",
            )
        )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "c1d2e3f4a5b6:bfca7016cbb7", "--sql"],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Alembic offline downgrade SQL generation failed (exit {result.returncode}):\n"
            f"{result.stderr}"
        )

    return result.stdout.lower()


class TestCompositeForeignKeyMigration:
    """DB-free checks that R2 migration declares composite tenant-scoped FKs."""

    def test_parent_scans_unique_constraint(self, migration_sql: str) -> None:
        assert re.search(
            r"alter table scans add constraint uq_scans_id_tenant_id unique \(id, tenant_id\)",
            migration_sql,
        )

    def test_parent_assets_unique_constraint(self, migration_sql: str) -> None:
        assert re.search(
            r"alter table assets add constraint uq_assets_id_tenant_id unique \(id, tenant_id\)",
            migration_sql,
        )

    def test_vulnerabilities_composite_fk(self, migration_sql: str) -> None:
        assert re.search(
            r"(?:alter table vulnerabilities add )?constraint fk_vulnerabilities_scan_tenant "
            r"foreign key\(scan_id, tenant_id\) references scans \(id, tenant_id\)",
            migration_sql,
        )

    def test_reports_composite_fk(self, migration_sql: str) -> None:
        assert re.search(
            r"(?:alter table reports add )?constraint fk_reports_asset_tenant "
            r"foreign key\(asset_id, tenant_id\) references assets \(id, tenant_id\)",
            migration_sql,
        )

    def test_scans_composite_fk_rollout_contract(self, migration_sql: str) -> None:
        assert "fk_scans_asset_tenant" in migration_sql
        assert "ix_scans_asset_tenant" in migration_sql
        assert "not valid" in migration_sql
        assert "validate constraint fk_scans_asset_tenant" in migration_sql
        assert "scans_asset_id_fkey" in migration_sql
        assert "cross-tenant scan/asset rows" in migration_sql

    def test_scans_composite_fk_downgrade_contract(self, migration_downgrade_sql: str) -> None:
        assert "drop constraint fk_scans_asset_tenant" in migration_downgrade_sql
        assert "drop index ix_scans_asset_tenant" in migration_downgrade_sql
        assert "create index ix_scans_asset_id" in migration_downgrade_sql
        assert "scans_asset_id_fkey" in migration_downgrade_sql
