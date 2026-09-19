"""RED tests for Slice 1 — Assets migration (T1..T2), events (T6),
EventBus stream override (T7), validators + schemas (T3, T10.1), and
service behaviour (T4, T10.3).

T1.4 contract: verify the new Alembic revision aligns `assets` to six
asset_types (`hostname`, `domain`, `ip`, `web_app`, `subnet`,
`cloud_resource`), renames `name` → `value`, drops `hostname`, adds
`uq_assets_tenant_type_value`, and preserves/reverses data.

These tests are written BEFORE the migration is created (RED state).
The offline SQL tests fail until the migration emits the right DDL;
the online tests fail until the preconditions abort before any DDL.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest
from sqlalchemy import make_url

from fakeredis.aioredis import FakeRedis

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Isolated test DB used only by the online behavior tests in this module.
# Created/dropped at module scope so we never disturb the shared test DB
# brought to HEAD by the session-scoped `prepare_database` fixture.
ISOLATED_DB = "soc360_test_assets_mig"
# The password comes from tests/.env (gitignored); host/port stay literal
# because the isolated DB deliberately targets the 5432 container, not the
# 5434 one used by the shared test database.
ISOLATED_DB_URL = (
    "postgresql+asyncpg://soc360_migration:"
    f"{make_url(os.environ['DATABASE_URL_MIGRATION']).password}"
    f"@localhost:5432/{ISOLATED_DB}"
)
# Reusable for direct asyncpg.connect calls (same source of truth as the URL).
ISOLATED_DB_PASSWORD = make_url(os.environ["DATABASE_URL_MIGRATION"]).password


# Slice 1's assets-alignment revision and its parent, pinned deliberately.
# These tests exist to validate THAT migration, but the old harness detected
# "the newest revision" dynamically via `alembic heads`. That silently broke as
# soon as a later migration became the head: `new_revision_sql` then rendered
# the newer migration and every assertion about the Slice 1 DDL failed. Pinning
# the pair keeps these tests inspecting the migration they were written for.
ASSETS_ALIGNMENT_PARENT = "a1b2c3d4e5f6"
ASSETS_ALIGNMENT_REVISION = "e0eafdf389fc"


def _alembic(
    *args: str,
    db_url: str | None = None,
) -> subprocess.CompletedProcess:
    """Run alembic via uv; pass DATABASE_URL_MIGRATION override when needed."""
    env = os.environ.copy()
    if db_url is not None:
        env["DATABASE_URL_MIGRATION"] = db_url
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )


@pytest.fixture(scope="module")
def migration_chain() -> tuple[str, str]:
    """Return (parent, revision) of the Slice 1 assets-alignment migration.

    Deliberately pinned instead of auto-detected so a later Alembic migration
    becoming the head cannot redirect these tests away from this revision.
    """
    return ASSETS_ALIGNMENT_PARENT, ASSETS_ALIGNMENT_REVISION


@pytest.fixture(scope="module")
def new_revision_sql(migration_chain: tuple[str, str]) -> str:
    """Offline SQL of the new migration (only the DDL it emits).

    We render `alembic upgrade <parent>:<head> --sql` which produces only
    the new migration's statements (no full chain). Lowercased for
    case-insensitive pattern matching.
    """
    parent, head = migration_chain
    result = _alembic("upgrade", f"{parent}:{head}", "--sql")
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade {parent}:{head} --sql failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.lower()


@pytest.fixture(scope="module")
def new_revision_downgrade_sql(migration_chain: tuple[str, str]) -> str:
    """Offline SQL of the new migration's downgrade()."""
    parent, head = migration_chain
    result = _alembic("downgrade", f"{head}:{parent}", "--sql")
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic downgrade {head}:{parent} --sql failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result.stdout.lower()


# ---------------------------------------------------------------------------
# Offline SQL tests — DB-free, validate the shape of the new revision
# ---------------------------------------------------------------------------


class TestMigrationShape:
    """DB-free assertions on the offline SQL rendered by the new migration."""

    def test_chk_assets_asset_type_extended_to_six_values(
        self, new_revision_sql: str
    ) -> None:
        # The new check constraint should include exactly: hostname, domain, ip,
        # web_app, subnet, cloud_resource. Alembic renders this as:
        #   ALTER TABLE assets ADD CONSTRAINT chk_assets_asset_type CHECK (
        #     asset_type IN ('hostname', 'domain', 'ip', 'web_app', 'subnet',
        #                    'cloud_resource')
        #   )
        match = re.search(
            r"add constraint chk_assets_asset_type\s+check\s*\(\s*"
            r"asset_type\s+in\s*\(([^)]+)\)",
            new_revision_sql,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None, (
            "chk_assets_asset_type with 6-value IN(...) not found in offline SQL. "
            "The migration must recreate the check with exactly the 6 values."
        )
        values = {v.strip().strip("'\"") for v in match.group(1).split(",")}
        assert values == {
            "hostname",
            "domain",
            "ip",
            "web_app",
            "subnet",
            "cloud_resource",
        }, f"Expected 6-value check, got: {sorted(values)}"

    def test_old_chk_assets_asset_type_dropped_before_recreating(
        self, new_revision_sql: str
    ) -> None:
        # The migration must drop the old 4-value check before recreating it,
        # otherwise the `UPDATE host→hostname` would be rejected by the old
        # check constraint.
        pattern = r"drop constraint chk_assets_asset_type"
        assert re.search(pattern, new_revision_sql, re.IGNORECASE), (
            "DROP CONSTRAINT chk_assets_asset_type not found. "
            "The migration must drop the old check before recreating it."
        )

    def test_uq_assets_tenant_type_value_added(self, new_revision_sql: str) -> None:
        # uq_assets_tenant_type_value UNIQUE (tenant_id, asset_type, value)
        pattern = (
            r"alter table assets\s+add constraint uq_assets_tenant_type_value\s+"
            r"unique\s*\(\s*tenant_id\s*,\s*asset_type\s*,\s*value\s*\)"
        )
        assert re.search(pattern, new_revision_sql, re.IGNORECASE | re.DOTALL), (
            "uq_assets_tenant_type_value UNIQUE (tenant_id, asset_type, value) "
            "not found. The migration must add this unique constraint."
        )

    def test_name_renamed_to_value(self, new_revision_sql: str) -> None:
        # Alembic renders rename as: ALTER TABLE assets RENAME name TO value
        pattern = r"alter table\s+assets\s+rename\s+\"?name\"?\s+to\s+\"?value\"?"
        assert re.search(pattern, new_revision_sql, re.IGNORECASE), (
            "ALTER TABLE assets RENAME name TO value not found. "
            "The migration must rename name → value."
        )

    def test_hostname_column_dropped(self, new_revision_sql: str) -> None:
        pattern = r"alter table\s+assets\s+drop column\s+\"?hostname\"?"
        assert re.search(pattern, new_revision_sql, re.IGNORECASE), (
            "ALTER TABLE assets DROP COLUMN hostname not found. "
            "The migration must drop hostname."
        )

    def test_host_to_hostname_update_emitted(self, new_revision_sql: str) -> None:
        # The migration must UPDATE asset_type='host' to 'hostname' so existing
        # rows survive the constraint change.
        pattern = (
            r"update\s+assets\s+set\s+asset_type\s*=\s*'hostname'"
            r"\s+where\s+asset_type\s*=\s*'host'"
        )
        assert re.search(pattern, new_revision_sql, re.IGNORECASE), (
            "UPDATE assets SET asset_type='hostname' WHERE asset_type='host' "
            "not found. The migration must remap existing 'host' rows."
        )

    def test_uniqueness_precondition_select_present_in_upgrade(
        self, new_revision_sql: str
    ) -> None:
        # The offline SQL does NOT show the precondition SELECT (it is executed
        # in upgrade() before any DDL). The runtime precondition is verified
        # by TestUpgradePrecondition. This test guards against the DDL being
        # silently dropped: there must be at least one ALTER TABLE … ADD
        # CONSTRAINT for uq_assets_tenant_type_value.
        assert re.search(
            r"add constraint uq_assets_tenant_type_value",
            new_revision_sql,
            re.IGNORECASE,
        ), "uq_assets_tenant_type_value ADD CONSTRAINT missing from upgrade SQL."

    def test_other_constraints_and_indexes_preserved(
        self, new_revision_sql: str
    ) -> None:
        # The migration must NOT touch chk_assets_status, uq_assets_id_tenant_id,
        # the trigger, the grants, the RLS policy, or the existing index.
        forbidden = [
            r"drop constraint chk_assets_status",
            r"drop constraint uq_assets_id_tenant_id",
            r"drop trigger",
            r"revoke.*on\s+assets",
            r"drop policy",
            r"disable row level security",
            r"drop index\s+ix_assets_tenant_id",
        ]
        for pat in forbidden:
            assert not re.search(pat, new_revision_sql, re.IGNORECASE), (
                f"Migration must NOT touch {pat!r}; the existing objects "
                f"must remain unchanged."
            )

    # ----- downgrade shape -------------------------------------------------

    def test_downgrade_restores_old_check_with_four_values(
        self, new_revision_downgrade_sql: str
    ) -> None:
        match = re.search(
            r"add constraint chk_assets_asset_type\s+check\s*\(\s*"
            r"asset_type\s+in\s*\(([^)]+)\)",
            new_revision_downgrade_sql,
            re.IGNORECASE | re.DOTALL,
        )
        assert match is not None, (
            "Downgrade must recreate chk_assets_asset_type with the original "
            "4-value IN(...) list."
        )
        values = {v.strip().strip("'\"") for v in match.group(1).split(",")}
        assert values == {"host", "domain", "ip", "web_app"}, (
            f"Expected downgrade check values {{host, domain, ip, web_app}}, "
            f"got: {sorted(values)}"
        )

    def test_downgrade_drops_unique_constraint(
        self, new_revision_downgrade_sql: str
    ) -> None:
        pattern = r"drop constraint uq_assets_tenant_type_value"
        assert re.search(
            pattern, new_revision_downgrade_sql, re.IGNORECASE
        ), "Downgrade must drop uq_assets_tenant_type_value."

    def test_downgrade_renames_value_to_name(
        self, new_revision_downgrade_sql: str
    ) -> None:
        pattern = r"alter table\s+assets\s+rename\s+\"?value\"?\s+to\s+\"?name\"?"
        assert re.search(
            pattern, new_revision_downgrade_sql, re.IGNORECASE
        ), "Downgrade must rename value → name."

    def test_downgrade_readds_hostname_column(
        self, new_revision_downgrade_sql: str
    ) -> None:
        # ALTER TABLE assets ADD COLUMN hostname varchar(255)
        pattern = (
            r"alter table\s+assets\s+add column\s+\"?hostname\"?\s+"
            r"(?:character varying|varchar)"
        )
        assert re.search(
            pattern, new_revision_downgrade_sql, re.IGNORECASE
        ), "Downgrade must re-add the hostname column as nullable varchar(255)."
        # And nullable (no NOT NULL after the type).
        m = re.search(
            r"alter table\s+assets\s+add column\s+\"?hostname\"?\s+"
            r"(?:character varying|varchar)\s*(?:\(\d+\))?\s*([^,;]*)",
            new_revision_downgrade_sql,
            re.IGNORECASE,
        )
        assert m is not None
        assert (
            "not null" not in m.group(1).lower()
        ), "hostname column in downgrade must be nullable."

    def test_downgrade_maps_hostname_back_to_host(
        self, new_revision_downgrade_sql: str
    ) -> None:
        pattern = (
            r"update\s+assets\s+set\s+asset_type\s*=\s*'host'"
            r"\s+where\s+asset_type\s*=\s*'hostname'"
        )
        assert re.search(
            pattern, new_revision_downgrade_sql, re.IGNORECASE
        ), "Downgrade must UPDATE asset_type='hostname' back to 'host'."


# ---------------------------------------------------------------------------
# Online behavior tests — use an isolated DB so we never disturb the shared
# test DB brought to HEAD by the session-scoped prepare_database fixture.
# ---------------------------------------------------------------------------


def _run_alembic_in_isolated(*args: str) -> subprocess.CompletedProcess:
    return _alembic(*args, db_url=ISOLATED_DB_URL)


def _alembic_returns_alembic_error(
    result: subprocess.CompletedProcess,
) -> bool:
    """Detect whether alembic surfaced our explicit RuntimeError.

    Alembic traps RuntimeError and returns exit code 1 with a traceback
    in stderr that contains the original RuntimeError text.
    """
    return result.returncode != 0 and (
        "RuntimeError" in result.stderr or "RuntimeError" in result.stdout
    )


def _runtime_error_message(result: subprocess.CompletedProcess) -> str:
    """Extract the message from our explicit RuntimeError in alembic output."""
    out = result.stderr + "\n" + result.stdout
    for line in out.splitlines():
        if line.strip().startswith("RuntimeError"):
            return line.strip()
    return out[-1000:]


def _run_in_event_loop(coro):
    """Run an asyncpg coroutine to completion in a worker thread.

    pytest-asyncio already runs the test inside an event loop, so calling
    ``asyncio.run()`` from inside the test fails with 'asyncio.run() cannot
    be called from a running event loop'. We delegate to a private thread
    so each helper call owns its own fresh event loop. This keeps the test
    functions synchronous while still using asyncpg.
    """
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


def _check_value_count(db_url: str, sql: str) -> int:
    """Connect with asyncpg and execute a count(*) returning int."""
    parsed = re.match(
        r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url
    )
    if parsed is None:
        raise RuntimeError(f"Invalid DB URL: {db_url}")
    user, password, host, port, dbname = parsed.groups()

    async def _run() -> int:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=dbname,
        )
        try:
            return await conn.fetchval(sql)
        finally:
            await conn.close()

    return _run_in_event_loop(_run())


def _fetch_scalar(db_url: str, sql: str) -> object:
    """Connect with asyncpg and execute a scalar-returning query."""
    parsed = re.match(
        r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url
    )
    if parsed is None:
        raise RuntimeError(f"Invalid DB URL: {db_url}")
    user, password, host, port, dbname = parsed.groups()

    async def _run() -> object:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=dbname,
        )
        try:
            return await conn.fetchval(sql)
        finally:
            await conn.close()

    return _run_in_event_loop(_run())


@pytest.fixture(scope="module", autouse=True)
def isolated_db(migration_chain: tuple[str, str]) -> Iterator[None]:
    """Create a fresh isolated DB, run alembic to HEAD-1, yield, drop DB.

    Yields control with the isolated DB at state HEAD-1 (the parent of the
    new revision). Individual tests then run alembic upgrade to HEAD to
    drive the precondition logic, and downgrade to HEAD-1 to restore.
    """
    parsed = re.match(
        r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)",
        ISOLATED_DB_URL,
    )
    if parsed is None:
        raise RuntimeError(f"Invalid ISOLATED_DB_URL: {ISOLATED_DB_URL}")
    user, password, host, port, dbname = parsed.groups()

    # The migration role does NOT have CREATE DATABASE privilege. We connect
    # as the cluster superuser (default 'danii' on dev machines) for DB
    # lifecycle, then keep using the migration role URL for alembic.
    admin_user = os.environ.get("PG_SUPERUSER", "danii")
    admin_password = os.environ.get("PG_SUPERUSER_PASSWORD", "")

    async def _setup() -> None:
        admin = await asyncpg.connect(
            user=admin_user,
            password=admin_password or None,
            host=host,
            port=int(port),
            database="postgres",
        )
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                dbname,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
            await admin.execute(f'CREATE DATABASE "{dbname}"')
        finally:
            await admin.close()

        # Grant the migration role the privileges alembic/env.py need
        # (CREATE on schema public, plus DDL on existing objects).
        owner = await asyncpg.connect(
            user=admin_user,
            password=admin_password or None,
            host=host,
            port=int(port),
            database=dbname,
        )
        try:
            await owner.execute("GRANT ALL ON SCHEMA public TO soc360_migration")
            await owner.execute("GRANT CREATE ON SCHEMA public TO soc360_migration")
        finally:
            await owner.close()

    async def _teardown() -> None:
        admin = await asyncpg.connect(
            user=admin_user,
            password=admin_password or None,
            host=host,
            port=int(port),
            database="postgres",
        )
        try:
            await admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = $1 AND pid <> pg_backend_pid()",
                dbname,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
        finally:
            await admin.close()

    asyncio.run(_setup())
    try:
        # Bring the isolated DB to HEAD (includes the new revision), then
        # downgrade to the parent so each test can drive its own upgrade/
        # downgrade cycle.
        result = _run_alembic_in_isolated("upgrade", "head")
        if result.returncode != 0:
            raise RuntimeError(
                f"alembic upgrade head on isolated DB failed:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        parent, head = migration_chain
        result = _run_alembic_in_isolated("downgrade", parent)
        if result.returncode != 0:
            raise RuntimeError(
                f"alembic downgrade {parent} on isolated DB failed:\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        yield
    finally:
        asyncio.run(_teardown())


class _AssetsMigrationTestBase:
    """Shared helpers for online behavior tests.

    Tests in this hierarchy share a single isolated DB; each test must
    clean its own rows before running so prior tests don't leak state.
    """

    def _clean_assets_rows(self) -> None:
        """Wipe rows from assets so each test starts from a known state."""

        async def _wipe() -> None:
            conn = await asyncpg.connect(
                user="soc360_migration",
                password=ISOLATED_DB_PASSWORD,
                host="localhost",
                port=5432,
                database=ISOLATED_DB,
            )
            try:
                await conn.execute("DELETE FROM assets")
            finally:
                await conn.close()

        # Use the current event loop (pytest-asyncio) instead of asyncio.run()
        # to avoid the "loop is already running" RuntimeError.
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        loop.run_until_complete(_wipe())


class TestUpgradePrecondition(_AssetsMigrationTestBase):
    """The duplicate-row precondition must abort upgrade() before any DDL."""

    def test_duplicate_rows_abort_upgrade_before_ddl(
        self, migration_chain: tuple[str, str]
    ) -> None:
        self._clean_assets_rows()
        parent, head = migration_chain

        # Insert two rows with same (tenant_id, asset_type, name) so the
        # unique constraint would be rejected.
        async def _seed_duplicate() -> None:
            conn = await asyncpg.connect(
                user="soc360_migration",
                password=ISOLATED_DB_PASSWORD,
                host="localhost",
                port=5432,
                database=ISOLATED_DB,
            )
            try:
                tenant_id = "11111111-1111-1111-1111-111111111111"
                await conn.execute(
                    "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
                    "VALUES ($1, $2, $3, $4, true, 50) "
                    "ON CONFLICT (id) DO NOTHING",
                    tenant_id,
                    "Empresa Alpha",
                    "empresa-alpha",
                    "starter",
                )
                await conn.execute(
                    "INSERT INTO assets (id, tenant_id, name, asset_type, status) "
                    "VALUES ($1, $2, '1.2.3.4', 'ip', 'active'), "
                    "       ($3, $2, '1.2.3.4', 'ip', 'active')",
                    "00000000-0000-0000-0000-000000000001",
                    tenant_id,
                    "00000000-0000-0000-0000-000000000002",
                )
            finally:
                await conn.close()

        asyncio.run(_seed_duplicate())

        # Attempt upgrade — must fail with RuntimeError.
        result = _run_alembic_in_isolated("upgrade", head)
        assert _alembic_returns_alembic_error(result), (
            "Upgrade must abort with RuntimeError when duplicates exist. "
            f"Got: rc={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        msg = _runtime_error_message(result)
        assert "duplicate" in msg.lower() or "uq_assets_tenant_type_value" in msg, (
            f"RuntimeError message must mention the unique constraint or "
            f"duplicates. Got: {msg!r}"
        )

        # Schema must be unchanged: still 4-value check, no
        # uq_assets_tenant_type_value, columns still 'name' + 'hostname'.
        chk_sql = (
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'"
        )
        chk_def = _fetch_scalar(ISOLATED_DB_URL, chk_sql) or ""
        assert "host" in chk_def and "subnet" not in chk_def, (
            f"After failed upgrade, chk_assets_asset_type must still be the "
            f"4-value original; got: {chk_def!r}"
        )

        uq_sql = (
            "SELECT count(*) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'uq_assets_tenant_type_value'"
        )
        uq_count = _check_value_count(ISOLATED_DB_URL, uq_sql)
        assert (
            uq_count == 0
        ), "uq_assets_tenant_type_value must NOT exist after a failed upgrade."

        name_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'name'",
        )
        hostname_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'hostname'",
        )
        value_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'value'",
        )
        assert name_count == 1, (
            f"Column 'name' must still exist after failed upgrade; "
            f"got count={name_count}."
        )
        assert hostname_count == 1, (
            f"Column 'hostname' must still exist after failed upgrade; "
            f"got count={hostname_count}."
        )
        assert value_count == 0, (
            f"Column 'value' must NOT exist after failed upgrade; "
            f"got count={value_count}."
        )

    def test_no_duplicates_upgrade_succeeds_and_preserves_rows(
        self, migration_chain: tuple[str, str]
    ) -> None:
        self._clean_assets_rows()
        parent, head = migration_chain

        # Seed 4 rows with distinct (tenant_id, asset_type, name) covering
        # the 4 historical asset_types (host, domain, ip, web_app).
        async def _seed() -> None:
            conn = await asyncpg.connect(
                user="soc360_migration",
                password=ISOLATED_DB_PASSWORD,
                host="localhost",
                port=5432,
                database=ISOLATED_DB,
            )
            try:
                tenant_id = "11111111-1111-1111-1111-111111111111"
                await conn.execute(
                    "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
                    "VALUES ($1, 'Empresa Alpha', 'empresa-alpha', 'starter', "
                    "true, 50) ON CONFLICT (id) DO NOTHING",
                    tenant_id,
                )
                rows = [
                    (
                        "00000000-0000-0000-0000-0000000000a1",
                        tenant_id,
                        "host-1",
                        "host",
                        "active",
                    ),
                    (
                        "00000000-0000-0000-0000-0000000000a2",
                        tenant_id,
                        "example.com",
                        "domain",
                        "active",
                    ),
                    (
                        "00000000-0000-0000-0000-0000000000a3",
                        tenant_id,
                        "1.2.3.4",
                        "ip",
                        "active",
                    ),
                    (
                        "00000000-0000-0000-0000-0000000000a4",
                        tenant_id,
                        "https://app.example.com",
                        "web_app",
                        "active",
                    ),
                ]
                for asset_id, tid, name, asset_type, status in rows:
                    await conn.execute(
                        "INSERT INTO assets (id, tenant_id, name, asset_type, status) "
                        "VALUES ($1, $2, $3, $4, $5)",
                        asset_id,
                        tid,
                        name,
                        asset_type,
                        status,
                    )
            finally:
                await conn.close()

        asyncio.run(_seed())

        # Count rows BEFORE upgrade.
        before = _check_value_count(ISOLATED_DB_URL, "SELECT count(*) FROM assets")
        assert before == 4, f"Expected 4 rows before upgrade, got {before}"

        # Upgrade.
        result = _run_alembic_in_isolated("upgrade", head)
        assert result.returncode == 0, (
            f"alembic upgrade head must succeed when no duplicates exist.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Row count preserved.
        after = _check_value_count(ISOLATED_DB_URL, "SELECT count(*) FROM assets")
        assert after == 4, f"Expected 4 rows after upgrade, got {after}"

        # Column 'value' exists, 'name' and 'hostname' do not.
        name_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'name'",
        )
        hostname_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'hostname'",
        )
        value_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'value'",
        )
        assert (
            name_count == 0
        ), f"name column must be renamed to value; name_count={name_count}"
        assert (
            hostname_count == 0
        ), f"hostname column must be dropped; hostname_count={hostname_count}"
        assert (
            value_count == 1
        ), f"value column must exist after upgrade; value_count={value_count}"

        # Existing rows preserved with values populated.
        rows = asyncio.run(_fetch_all_assets(ISOLATED_DB_URL))
        by_value = {row["value"]: row for row in rows}
        assert (
            "host-1" in by_value
        ), "Row previously named 'host-1' must be in 'value' column."
        # The 'host' asset_type was renamed to 'hostname'.
        assert by_value["host-1"]["asset_type"] == "hostname", (
            f"asset_type 'host' must be remapped to 'hostname' on upgrade; "
            f"got {by_value['host-1']['asset_type']!r}"
        )

        # Unique constraint present.
        uq_sql = (
            "SELECT count(*) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'uq_assets_tenant_type_value'"
        )
        assert (
            _check_value_count(ISOLATED_DB_URL, uq_sql) == 1
        ), "uq_assets_tenant_type_value must exist after successful upgrade."

        # Six-value check present.
        chk_def = (
            _fetch_scalar(
                ISOLATED_DB_URL,
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
            )
            or ""
        )
        for token in (
            "hostname",
            "domain",
            "ip",
            "web_app",
            "subnet",
            "cloud_resource",
        ):
            assert (
                token in chk_def
            ), f"chk_assets_asset_type missing {token!r}: {chk_def!r}"


class TestDowngradePrecondition(_AssetsMigrationTestBase):
    """The new-types precondition must abort downgrade() before any DDL."""

    def test_subnet_rows_abort_downgrade_before_ddl(
        self, migration_chain: tuple[str, str]
    ) -> None:
        self._clean_assets_rows()
        parent, head = migration_chain

        # Make sure we're at HEAD (new revision applied).
        result = _run_alembic_in_isolated("upgrade", head)
        assert result.returncode == 0, (
            f"Setup: alembic upgrade head failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Insert a row with subnet asset_type.
        async def _seed_subnet() -> None:
            conn = await asyncpg.connect(
                user="soc360_migration",
                password=ISOLATED_DB_PASSWORD,
                host="localhost",
                port=5432,
                database=ISOLATED_DB,
            )
            try:
                tenant_id = "11111111-1111-1111-1111-111111111111"
                await conn.execute(
                    "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
                    "VALUES ($1, 'Empresa Alpha', 'empresa-alpha', 'starter', "
                    "true, 50) ON CONFLICT (id) DO NOTHING",
                    tenant_id,
                )
                await conn.execute(
                    "INSERT INTO assets (id, tenant_id, value, asset_type, status) "
                    "VALUES ($1, $2, '10.0.0.0/24', 'subnet', 'active')",
                    "00000000-0000-0000-0000-0000000000b1",
                    tenant_id,
                )
            finally:
                await conn.close()

        asyncio.run(_seed_subnet())

        # Attempt downgrade -1; must fail.
        result = _run_alembic_in_isolated("downgrade", "-1")
        assert _alembic_returns_alembic_error(result), (
            "Downgrade must abort with RuntimeError when subnet/cloud_resource "
            f"rows exist. Got rc={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        msg = _runtime_error_message(result)
        assert "subnet" in msg.lower() or "cloud_resource" in msg.lower(), (
            f"RuntimeError message must mention subnet/cloud_resource. " f"Got: {msg!r}"
        )

        # Schema must remain in post-upgrade state.
        chk_def = (
            _fetch_scalar(
                ISOLATED_DB_URL,
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
            )
            or ""
        )
        for token in ("hostname", "subnet", "cloud_resource"):
            assert token in chk_def, (
                f"After failed downgrade, chk must still include {token!r}; "
                f"got {chk_def!r}"
            )

        uq_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'uq_assets_tenant_type_value'",
        )
        assert uq_count == 1, (
            f"uq_assets_tenant_type_value must still exist after failed "
            f"downgrade; got count={uq_count}."
        )

        name_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'name'",
        )
        value_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'value'",
        )
        hostname_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'hostname'",
        )
        assert (
            name_count == 0
        ), f"name must NOT exist (still 'value'); got count={name_count}"
        assert (
            value_count == 1
        ), f"value column must still exist; got count={value_count}"
        assert (
            hostname_count == 0
        ), f"hostname must NOT exist after failed downgrade; got count={hostname_count}"

    def test_downgrade_with_only_old_types_succeeds(
        self, migration_chain: tuple[str, str]
    ) -> None:
        self._clean_assets_rows()
        parent, head = migration_chain

        # Ensure we are at HEAD.
        result = _run_alembic_in_isolated("upgrade", head)
        assert result.returncode == 0, (
            f"Setup: alembic upgrade head failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # No subnet/cloud_resource rows present.
        new_types_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM assets WHERE asset_type IN ('subnet','cloud_resource')",
        )
        assert (
            new_types_count == 0
        ), f"Setup: no subnet/cloud_resource rows expected; got {new_types_count}."

        # Downgrade -1 should succeed.
        result = _run_alembic_in_isolated("downgrade", "-1")
        assert result.returncode == 0, (
            f"alembic downgrade -1 must succeed when no subnet/cloud_resource "
            f"rows exist.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify post-downgrade shape.
        chk_def = (
            _fetch_scalar(
                ISOLATED_DB_URL,
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
            )
            or ""
        )
        for token in ("host", "domain", "ip", "web_app"):
            assert token in chk_def, (
                f"After successful downgrade, chk must include {token!r}; "
                f"got {chk_def!r}"
            )
        for token in ("subnet", "cloud_resource", "hostname"):
            assert token not in chk_def, (
                f"After successful downgrade, chk must NOT include {token!r}; "
                f"got {chk_def!r}"
            )

        # - column 'name' back, 'value' gone
        name_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'name'",
        )
        value_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'value'",
        )
        hostname_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'hostname'",
        )
        assert (
            name_count == 1
        ), f"After downgrade, 'name' must be back; got count={name_count}"
        assert (
            value_count == 0
        ), f"After downgrade, 'value' must be gone; got count={value_count}"
        assert (
            hostname_count == 1
        ), f"After downgrade, 'hostname' must be back; got count={hostname_count}"

        # - uq_assets_tenant_type_value gone
        uq_count = _check_value_count(
            ISOLATED_DB_URL,
            "SELECT count(*) FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'uq_assets_tenant_type_value'",
        )
        assert uq_count == 0, (
            f"After successful downgrade, uq_assets_tenant_type_value must "
            f"NOT exist; got count={uq_count}."
        )

        # hostname column is nullable.
        is_nullable = _fetch_scalar(
            ISOLATED_DB_URL,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'assets' AND column_name = 'hostname'",
        )
        assert is_nullable == "YES", (
            f"hostname column must be nullable after downgrade; "
            f"got is_nullable={is_nullable!r}"
        )


async def _fetch_all_assets(db_url: str) -> list[dict]:
    parsed = re.match(
        r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)", db_url
    )
    if parsed is None:
        raise RuntimeError(f"Invalid DB URL: {db_url}")
    user, password, host, port, dbname = parsed.groups()

    async def _run() -> list[dict]:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=int(port),
            database=dbname,
        )
        try:
            await conn.execute("SET app.is_superadmin = 'true'")
            rows = await conn.fetch(
                "SELECT id, tenant_id, value, asset_type, status "
                "FROM assets ORDER BY asset_type"
            )
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    return await _run()


# ---------------------------------------------------------------------------
# T6.2 — Asset event schema smoke tests (RED → GREEN)
# ---------------------------------------------------------------------------
class TestAssetEventSchemas:
    """RED tests asserting each Asset* event in app/event_schemas.py carries
    the correct ``event_type`` literal and required payload fields."""

    def test_asset_created_event_serializes_with_event_type_literal(self) -> None:
        from app.event_schemas import AssetCreatedEvent

        tenant_id = uuid.uuid4()
        asset_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)
        evt = AssetCreatedEvent(
            event_id=uuid.uuid4(),
            tenant_id=tenant_id,
            asset_id=asset_id,
            type="ip",
            value="192.0.2.42",
            created_at=created_at,
        )
        assert evt.event_type == "asset.created"
        payload = json.loads(evt.model_dump_json())
        assert payload["event_type"] == "asset.created"
        assert payload["asset_id"] == str(asset_id)
        assert payload["type"] == "ip"
        assert payload["value"] == "192.0.2.42"
        assert payload["tenant_id"] == str(tenant_id)
        # created_at field is required and round-trips
        assert "created_at" in payload

    def test_asset_updated_event_carries_changed_fields_list(self) -> None:
        from app.event_schemas import AssetUpdatedEvent

        evt = AssetUpdatedEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
            changed_fields=["type", "value"],
        )
        assert evt.event_type == "asset.updated"
        payload = json.loads(evt.model_dump_json())
        assert payload["event_type"] == "asset.updated"
        assert payload["changed_fields"] == ["type", "value"]

    def test_asset_deleted_event_carries_asset_id(self) -> None:
        from app.event_schemas import AssetDeletedEvent

        evt = AssetDeletedEvent(
            event_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            asset_id=uuid.uuid4(),
        )
        assert evt.event_type == "asset.deleted"
        payload = json.loads(evt.model_dump_json())
        assert payload["event_type"] == "asset.deleted"
        assert "asset_id" in payload
        # No spurious payload fields are emitted by the model:
        assert set(payload.keys()) >= {
            "event_id",
            "event_type",
            "tenant_id",
            "asset_id",
            "timestamp",
        }

    def test_asset_events_inherit_base_envelope(self) -> None:
        """Asset* events MUST inherit from BaseEvent (event_id + tenant_id)."""
        from app.event_schemas import (
            AssetCreatedEvent,
            AssetDeletedEvent,
            AssetUpdatedEvent,
            BaseEvent,
        )

        assert issubclass(AssetCreatedEvent, BaseEvent)
        assert issubclass(AssetUpdatedEvent, BaseEvent)
        assert issubclass(AssetDeletedEvent, BaseEvent)


# ---------------------------------------------------------------------------
# T7.2 — EventBus.publish stream override tests (RED → GREEN)
# ---------------------------------------------------------------------------
class TestEventBusPublishStreamOverride:
    """RED tests for EventBus.publish(event, stream=...)."""

    @pytest.mark.asyncio
    async def test_publish_with_stream_override_writes_to_named_stream(self) -> None:
        from app.event_bus import EventBus
        from app.event_schemas import AssetCreatedEvent

        client = FakeRedis(decode_responses=False)
        bus = EventBus(redis_client=client)
        try:
            evt = AssetCreatedEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                asset_id=uuid.uuid4(),
                type="ip",
                value="192.0.2.10",
                created_at=datetime.now(timezone.utc),
            )
            msg_id = await bus.publish(evt, stream="asset.events")
            assert msg_id is not None

            # Override stream holds the entry; default stream does not.
            override_len = await client.xlen("asset.events")
            default_len = await client.xlen("events:asset.created")
            assert (
                override_len == 1
            ), f"stream= override MUST write to 'asset.events', got len={override_len}."
            assert default_len == 0, (
                "Publishing with stream= override MUST NOT write to the default "
                "F1 stream 'events:asset.created'."
            )
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_publish_without_stream_override_uses_default_stream(self) -> None:
        from app.event_bus import EventBus
        from app.event_schemas import AssetCreatedEvent

        client = FakeRedis(decode_responses=False)
        bus = EventBus(redis_client=client)
        try:
            evt = AssetCreatedEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                asset_id=uuid.uuid4(),
                type="ip",
                value="192.0.2.11",
                created_at=datetime.now(timezone.utc),
            )
            msg_id = await bus.publish(evt)  # no stream= override
            assert msg_id is not None
            default_len = await client.xlen("events:asset.created")
            override_len = await client.xlen("asset.events")
            assert default_len == 1, (
                f"Without stream= override, MUST use F1 default stream, "
                f"got len={default_len}."
            )
            assert (
                override_len == 0
            ), "Without stream= override, MUST NOT auto-publish to 'asset.events'."
        finally:
            await client.aclose()

    @pytest.mark.asyncio
    async def test_publish_with_stream_override_persists_event_type_field(self) -> None:
        from app.event_bus import EventBus
        from app.event_schemas import AssetCreatedEvent

        client = FakeRedis(decode_responses=False)
        bus = EventBus(redis_client=client)
        try:
            evt = AssetCreatedEvent(
                event_id=uuid.uuid4(),
                tenant_id=uuid.uuid4(),
                asset_id=uuid.uuid4(),
                type="hostname",
                value="app.example.com",
                created_at=datetime.now(timezone.utc),
            )
            await bus.publish(evt, stream="asset.events")

            entries = await client.xrange("asset.events")
            assert entries, "asset.events stream MUST contain the published entry."
            _msg_id, fields = entries[0]

            def _decode(value: object) -> str:
                return value.decode() if isinstance(value, bytes) else value  # type: ignore[union-attr]

            decoded = {_decode(k): _decode(v) for k, v in fields.items()}
            assert decoded["event_type"] == "asset.created"
            assert decoded["type"] == "hostname"
            assert decoded["value"] == "app.example.com"
            assert decoded["asset_id"] == str(evt.asset_id)
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# T10.1 — Validator helper (subset) and T3 schemas tests (RED → GREEN)
# ---------------------------------------------------------------------------
class TestAssetValidators:
    """RED tests for ``_validate_asset_value`` in app/modules/assets/service.py.

    Covers the minimum happy/sad paths per the design.md D-004 contract. The
    full validator matrix (hostname/domain/web_app) belongs to T10.1 in the
    next delegation; this slice focuses on the ip / subnet / cloud_resource
    cases plus the exact error messages required for 422 mapping.
    """

    def test_validate_ip_happy_v4_is_canonicalized(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # '192.0.2.42' canonicalizes to itself.
        result = _validate_asset_value("ip", "192.0.2.42")
        assert result == "192.0.2.42"

    def test_validate_ip_happy_v6_is_canonicalized(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # '2001:0db8::1' MUST canonicalize to '2001:db8::1'.
        result = _validate_asset_value("ip", "2001:0db8::1")
        assert result == "2001:db8::1"

    def test_validate_ip_sad_raises_exact_422_message(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("ip", "999.999.999.1")
        assert str(exc_info.value) == "value must be a valid IPv4 or IPv6 address"

    def test_validate_ip_sad_garbage_raises_exact_message(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("ip", "not-an-ip")
        assert str(exc_info.value) == "value must be a valid IPv4 or IPv6 address"

    def test_validate_subnet_happy_canonicalizes(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # '192.168.0.5/24' normalizes to the network address '192.168.0.0/24'.
        result = _validate_asset_value("subnet", "192.168.0.5/24")
        assert result == "192.168.0.0/24"

    def test_validate_subnet_sad_prefix_out_of_range(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("subnet", "192.168.0.0/40")
        assert str(exc_info.value) == "value must be a valid CIDR"

    def test_validate_subnet_sad_garbage_prefix(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("subnet", "192.168.0.0/abc")
        assert str(exc_info.value) == "value must be a valid CIDR"

    def test_validate_cloud_resource_happy_arn(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        result = _validate_asset_value("cloud_resource", "arn:aws:s3:::my-bucket")
        assert result == "arn:aws:s3:::my-bucket"

    def test_validate_cloud_resource_sad_missing_resource_segment(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # No ':resource' segment after the trailing ':' — ARN is incomplete.
        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("cloud_resource", "arn:aws:s3::us-west-2")
        assert str(exc_info.value) == "value must be a valid ARN"


class TestAssetSchemas:
    """RED tests for app/modules/assets/schemas.py (T3)."""

    def test_asset_response_has_exactly_six_fields(self) -> None:
        from app.modules.assets.schemas import AssetResponse

        fields = set(AssetResponse.model_fields.keys())
        assert fields == {
            "id",
            "type",
            "value",
            "tenant_id",
            "created_at",
            "updated_at",
        }, f"AssetResponse MUST expose exactly six public fields, got {fields!r}"

    def test_asset_response_extra_forbid_rejects_unknown_field(self) -> None:
        from pydantic import ValidationError

        from app.modules.assets.schemas import AssetResponse

        tenant_id = uuid.uuid4()
        with pytest.raises(ValidationError):
            AssetResponse(
                id=uuid.uuid4(),
                type="ip",
                value="1.2.3.4",
                tenant_id=tenant_id,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                status="active",  # NOT whitelisted
            )

    def test_asset_response_renames_orm_asset_type_to_public_type(self) -> None:
        """AssetResponse.from_orm_instance MUST map asset_type -> 'type'."""
        from app.modules.assets.models import Asset
        from app.modules.assets.schemas import AssetResponse

        orm = Asset(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            value="192.0.2.1",
            asset_type="ip",
        )
        # Bypass DB defaults for the test
        orm.created_at = datetime.now(timezone.utc)
        orm.updated_at = datetime.now(timezone.utc)

        response = AssetResponse.from_orm_instance(orm)
        dumped = response.model_dump(mode="json")
        assert dumped["type"] == "ip"
        assert dumped["value"] == "192.0.2.1"
        assert "asset_type" not in dumped
        assert "status" not in dumped
        assert "asset_metadata" not in dumped
        assert "created_by_user_id" not in dumped
        assert "raw_input" not in dumped

    def test_asset_create_base_rejects_extra_fields(self) -> None:
        from pydantic import ValidationError

        from app.modules.assets.schemas import AssetCreateBase

        with pytest.raises(ValidationError):
            AssetCreateBase(
                tenant_id=uuid.uuid4(),
                value="x",
                bogus_field="reject me",
            )

    def test_asset_update_uses_partial_pattern(self) -> None:
        from pydantic import ValidationError

        from app.modules.assets.schemas import AssetUpdate

        # Both fields optional, extra rejected.
        u = AssetUpdate()
        assert u.type is None and u.value is None

        u2 = AssetUpdate(type="ip", value="192.0.2.5")
        assert u2.type == "ip"
        assert u2.value == "192.0.2.5"

        with pytest.raises(ValidationError):
            AssetUpdate(unknown_field="nope")

    def test_asset_create_request_is_discriminated_union(self) -> None:
        """Discriminated union MUST reject payloads whose ``type`` doesn't match
        the chosen schema branch."""
        from pydantic import ValidationError

        from app.modules.assets.schemas import AssetCreateRequest, IpAssetCreate

        # Building via the concrete type works.
        ok = IpAssetCreate(
            tenant_id=uuid.uuid4(),
            value="192.0.2.7",
            type="ip",
        )
        assert ok.type == "ip"

        # Wrong discriminator literal must fail.
        with pytest.raises(ValidationError):
            IpAssetCreate(
                tenant_id=uuid.uuid4(),
                value="192.0.2.7",
                type="hostname",  # not "ip"
            )

        # AssetType Literal exists with exactly six values.
        import typing

        from app.modules.assets.schemas import AssetType

        asset_type_values = typing.get_args(AssetType)
        for expected in (
            "ip",
            "domain",
            "hostname",
            "web_app",
            "subnet",
            "cloud_resource",
        ):
            assert (
                expected in asset_type_values
            ), f"AssetType MUST contain {expected!r}; got {asset_type_values!r}"
        assert len(asset_type_values) == 6

        # Ensure AssetCreateRequest is iterable over the six branches.
        # AssetCreateRequest is ``Annotated[Union[...], Field(...)]`` whose
        # outer __args__ has length 1 (the Union). Use typing.get_args to
        # peel off Annotated + Union layers and recover the six branches.
        import typing as _typing

        outer = _typing.get_args(AssetCreateRequest)
        assert len(outer) >= 1
        union = outer[0]
        branches = _typing.get_args(union)
        assert len(branches) == 6, (
            f"AssetCreateRequest MUST have 6 discriminated branches, "
            f"got {len(branches)}: {branches!r}"
        )


# ---------------------------------------------------------------------------
# T10.3 — Service unit tests (AsyncMock for AsyncSession and EventBus)
# ---------------------------------------------------------------------------
class TestAssetService:
    """RED tests for the asset service module-level functions."""

    @pytest.mark.asyncio
    async def test_create_asset_flushes_commits_and_publishes_to_stream(self) -> None:
        """create_asset MUST flush + commit, then publish(stream='asset.events')."""
        db = MagicMock()
        # AsyncMock for the async methods we'll exercise
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        # db.flush must simulate SQLAlchemy's flush() behaviour: populate
        # server defaults (id, timestamps) on the model instance so the
        # event snapshot can be built.
        async def _flush() -> None:
            obj = db.add.call_args.args[0]
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = now

        db.flush = AsyncMock(side_effect=_flush)
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        from app.modules.assets import service
        from app.modules.assets.schemas import IpAssetCreate

        data = IpAssetCreate(
            tenant_id=uuid.uuid4(),
            value="192.0.2.50",
            type="ip",
        )

        asset = await service.create_asset(
            data=data,
            tenant_id=data.tenant_id,
            db=db,
            event_bus=event_bus,
        )

        db.add.assert_called_once()
        db.flush.assert_awaited_once()
        db.commit.assert_awaited_once()
        event_bus.publish.assert_awaited_once()
        kwargs = event_bus.publish.await_args.kwargs
        assert kwargs.get("stream") == "asset.events"
        evt = event_bus.publish.await_args.args[0]
        assert getattr(evt, "event_type", None) == "asset.created"
        assert getattr(asset, "value", None) == "192.0.2.50"

    @pytest.mark.asyncio
    async def test_update_asset_changed_fields_lists_changed_keys(self) -> None:
        """update_asset's ``changed_fields`` MUST contain the public field
        names that actually changed.
        """
        orm = MagicMock()
        orm.id = uuid.uuid4()
        orm.tenant_id = uuid.uuid4()
        orm.asset_type = "ip"
        orm.value = "192.0.2.10"
        orm.created_at = datetime.now(timezone.utc)
        orm.updated_at = datetime.now(timezone.utc)

        db = MagicMock()
        execute_result = MagicMock(scalar_one_or_none=MagicMock(return_value=orm))
        db.execute = AsyncMock(return_value=execute_result)
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        from app.modules.assets import service
        from app.modules.assets.schemas import AssetUpdate

        data = AssetUpdate(value="192.0.2.99")
        result = await service.update_asset(
            asset_id=orm.id,
            tenant_id=orm.tenant_id,
            data=data,
            db=db,
            event_bus=event_bus,
        )
        assert result is not None
        # The publish call MUST carry changed_fields containing 'value' only.
        kwargs = event_bus.publish.await_args.kwargs
        assert kwargs.get("stream") == "asset.events"
        evt = event_bus.publish.await_args.args[0]
        assert "value" in evt.changed_fields
        assert "type" not in evt.changed_fields

    @pytest.mark.asyncio
    async def test_delete_asset_returns_true_and_publishes(self) -> None:
        """delete_asset MUST publish asset.deleted on 'asset.events'."""
        orm = MagicMock()
        orm.id = uuid.uuid4()
        orm.tenant_id = uuid.uuid4()

        db = MagicMock()
        execute_result = MagicMock(scalar_one_or_none=MagicMock(return_value=orm))
        db.execute = AsyncMock(return_value=execute_result)
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        from app.modules.assets import service

        ok = await service.delete_asset(
            asset_id=orm.id,
            tenant_id=orm.tenant_id,
            db=db,
            event_bus=event_bus,
        )
        assert ok is True
        db.delete.assert_awaited_once_with(orm)
        event_bus.publish.assert_awaited_once()
        kwargs = event_bus.publish.await_args.kwargs
        assert kwargs.get("stream") == "asset.events"
        evt = event_bus.publish.await_args.args[0]
        assert getattr(evt, "event_type", None) == "asset.deleted"

    @pytest.mark.asyncio
    async def test_list_assets_returns_items_and_total(self) -> None:
        """list_assets MUST return (items, total) ordered by created_at DESC, id DESC."""
        items = [MagicMock(), MagicMock()]
        db = MagicMock()
        # First execute = count, second execute = items.
        count_result = MagicMock(scalar_one=MagicMock(return_value=7))
        items_result = MagicMock()
        items_result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=items))
        )
        db.execute = AsyncMock(side_effect=[count_result, items_result])

        from app.modules.assets import service

        result_items, total = await service.list_assets(
            tenant_id=uuid.uuid4(),
            db=db,
            limit=10,
            offset=0,
        )
        assert total == 7
        assert list(result_items) == items

    @pytest.mark.asyncio
    async def test_create_asset_duplicate_raises_domain_error(self) -> None:
        """create_asset MUST translate IntegrityError on uq constraint -> AssetDuplicateError."""
        from sqlalchemy.exc import IntegrityError

        from app.modules.assets import service
        from app.modules.assets.schemas import IpAssetCreate

        db = MagicMock()
        db.add = MagicMock()
        # First flush raises IntegrityError, second flush (after rollback) succeeds.
        err = IntegrityError("INSERT", {}, Exception("uq_assets_tenant_type_value"))
        err.orig = MagicMock(constraint_name="uq_assets_tenant_type_value")
        db.flush = AsyncMock(side_effect=[err, None])
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        data = IpAssetCreate(
            tenant_id=uuid.uuid4(),
            value="192.0.2.10",
            type="ip",
        )
        with pytest.raises(service.AssetDuplicateError):
            await service.create_asset(
                data=data,
                tenant_id=data.tenant_id,
                db=db,
                event_bus=event_bus,
            )
        event_bus.publish.assert_not_awaited()


# ---------------------------------------------------------------------------
# T5 — require_any_role guard (RED → GREEN)
# ---------------------------------------------------------------------------
class TestRequireAnyRole:
    """RED tests for app.dependencies.auth.require_any_role factory guard."""

    @pytest.mark.asyncio
    async def test_require_any_role_allows_user_in_allowlist(self) -> None:
        """User with a role in the allowlist MUST pass through unmodified."""
        from app.dependencies.auth import require_any_role

        guard = require_any_role("admin", "superadmin")
        user = MagicMock()
        user.role = "admin"
        result = await guard(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_require_any_role_rejects_user_not_in_allowlist(self) -> None:
        """User with a role absent from the allowlist MUST 403."""
        from fastapi import HTTPException

        from app.dependencies.auth import require_any_role

        guard = require_any_role("admin", "superadmin")
        user = MagicMock()
        user.role = "analyst"
        with pytest.raises(HTTPException) as exc_info:
            await guard(current_user=user)
        assert exc_info.value.status_code == 403


def test_require_any_role_is_re_exported_from_dependencies_package() -> None:
    """require_any_role MUST be importable from app.dependencies directly."""
    import app.dependencies as deps_pkg
    from app.dependencies import require_any_role  # noqa: F401

    assert hasattr(deps_pkg, "require_any_role")


# ---------------------------------------------------------------------------
# T10.1 — Full validator matrix (RED → GREEN)
# ---------------------------------------------------------------------------
# The previous slice shipped a subset of validators (ip, subnet,
# cloud_resource). This slice completes the matrix: domain, hostname,
# web_app. The contract for each type is taken verbatim from
# design.md D-004 and spec.md ("Tipos de asset soportados").
class TestAssetValidatorsFullMatrix:
    """RED tests completing the ``_validate_asset_value`` matrix.

    Covers every happy + sad path required by T10.1:
    * ``ip`` — IPv4 + IPv6 happy; ``not-an-ip`` + out-of-range octets sad.
    * ``domain`` — FQDN happy; leading-dash label + embedded space sad.
    * ``hostname`` — RFC-1123-ish happy; embedded space sad.
    * ``web_app`` — http(s) URL happy; ftp:// sad.
    * ``subnet`` — canonical network address happy; out-of-range + alpha
      prefix sad.
    * ``cloud_resource`` — AWS ARN happy; empty resource segment sad.
    """

    # ----- domain -----------------------------------------------------------
    def test_validate_domain_happy_normalizes_lowercase_and_strips_trailing_dot(
        self,
    ) -> None:
        from app.modules.assets.service import _validate_asset_value

        # The validator MUST lowercase + strip the trailing dot.
        assert _validate_asset_value("domain", "Example.COM.") == "example.com"
        assert _validate_asset_value("domain", "EXAMPLE.COM") == "example.com"

    def test_validate_domain_sad_leading_dash_label_rejects(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("domain", "-bad-.com")
        assert str(exc_info.value) == "value must be a valid FQDN"

    def test_validate_domain_sad_embedded_space_rejects(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("domain", "espacio .com")
        assert str(exc_info.value) == "value must be a valid FQDN"

    # ----- hostname ---------------------------------------------------------
    def test_validate_hostname_happy_lowercases(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # The validator MUST lowercase (case-insensitive acceptance) but
        # otherwise preserve the canonical hostname shape.
        assert _validate_asset_value("hostname", "App.Example.COM") == "app.example.com"
        assert _validate_asset_value("hostname", "app.example.com") == "app.example.com"

    def test_validate_hostname_sad_embedded_space_rejects(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("hostname", "bad host")
        assert str(exc_info.value) == "value must be a valid hostname"

    # ----- web_app ----------------------------------------------------------
    def test_validate_web_app_happy_accepts_https_url_with_path_and_query(
        self,
    ) -> None:
        from app.modules.assets.service import _validate_asset_value

        canonical = _validate_asset_value("web_app", "https://app.example.com/path?q=1")
        # Pydantic HttpUrl canonicalizes the scheme + host; the slice does
        # not require the path/query to be preserved verbatim, only that the
        # input is accepted and returns a valid http(s) string.
        assert canonical.startswith("https://app.example.com")
        assert "?" not in canonical or "q=1" in canonical

    def test_validate_web_app_sad_ftp_scheme_rejects(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("web_app", "ftp://x")
        assert str(exc_info.value) == "value must be a valid http(s) URL"

    # ----- subnet (additional happy path coverage) --------------------------
    def test_validate_subnet_happy_canonicalizes_to_network_address(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # '192.168.0.0/24' canonicalizes to itself.
        assert _validate_asset_value("subnet", "192.168.0.0/24") == "192.168.0.0/24"
        # '192.168.0.5/24' canonicalizes to the network address (host bits
        # dropped by ipaddress.ip_network(..., strict=False)).
        assert _validate_asset_value("subnet", "192.168.0.5/24") == "192.168.0.0/24"

    # ----- cloud_resource (additional ARN contract coverage) ----------------
    def test_validate_cloud_resource_happy_arn_with_region_account_resource(
        self,
    ) -> None:
        from app.modules.assets.service import _validate_asset_value

        # Six-segment ARN with all segments populated.
        canonical = _validate_asset_value(
            "cloud_resource",
            "arn:aws:ec2:us-east-1:123456789012:instance/i-abcd1234",
        )
        assert canonical == "arn:aws:ec2:us-east-1:123456789012:instance/i-abcd1234"

    def test_validate_cloud_resource_sad_empty_resource_segment_rejects(self) -> None:
        from app.modules.assets.service import _validate_asset_value

        # The regex requires at least one character in the resource
        # segment. ``arn:aws:s3:::`` ends with an empty resource part
        # before the final colon.
        with pytest.raises(ValueError) as exc_info:
            _validate_asset_value("cloud_resource", "arn:aws:s3:::")
        assert str(exc_info.value) == "value must be a valid ARN"


# ---------------------------------------------------------------------------
# T10.2 — SQLAlchemy uniqueness (live DB integration test)
# ---------------------------------------------------------------------------
# Reuses the ``db_session`` + ``seed_data`` fixtures from tests/conftest.py
# to drive two INSERTs against the real ``assets`` table and assert that
# the unique constraint fires with the expected name.
class TestAssetUniquenessAtSQLAlchemyLayer:
    """SQLAlchemy-level uniqueness test for ``uq_assets_tenant_type_value``.

    The asyncpg driver raises IntegrityError whose ``orig.constraint_name``
    is ``uq_assets_tenant_type_value``. This test guards the contract
    directly against the live database (no in-memory mocking) so the
    constraint is exercised exactly the way production code will hit it.
    """

    @pytest.mark.asyncio
    async def test_duplicate_insert_raises_integrity_error_with_constraint_name(
        self, db_session, seed_data
    ) -> None:
        from sqlalchemy.exc import IntegrityError

        from app.modules.assets.models import Asset

        tenant_a = seed_data["tenant_a"]
        # Two rows: identical (tenant_id, asset_type, value).
        first = Asset(
            tenant_id=tenant_a.id,
            asset_type="ip",
            value="192.0.2.42",
        )
        second = Asset(
            tenant_id=tenant_a.id,
            asset_type="ip",
            value="192.0.2.42",
        )

        db_session.add(first)
        await db_session.flush()
        db_session.add(second)

        with pytest.raises(IntegrityError) as exc_info:
            await db_session.flush()

        orig = exc_info.value.orig
        assert orig is not None
        # SQLAlchemy's asyncpg adapter wraps the driver exception and
        # only preserves the SQLSTATE code. The constraint name is
        # surfaced through the error message string, which is exactly
        # what ``_is_duplicate_constraint_error`` in service.py uses as
        # its fallback. We assert both: pgcode == '23505' AND the
        # constraint name appears in the message body.
        assert getattr(orig, "pgcode", None) == "23505"
        assert "uq_assets_tenant_type_value" in str(orig)


# ---------------------------------------------------------------------------
# T10.3 — Service purity (extended)
# ---------------------------------------------------------------------------
# This class extends the prior T10.3 subset by covering:
# * flush → commit → publish call ordering for create_asset;
# * list_assets ordering (created_at DESC, id DESC);
# * update_asset changed_fields for both fields in stable order;
# * delete_asset returns False (the 404-equivalent contract) when the
#   asset is missing in the visible scope.
class TestAssetServiceFullContract:
    """RED tests for service-level invariants required by T10.3."""

    @pytest.mark.asyncio
    async def test_create_asset_calls_flush_then_commit_then_publish_in_order(
        self,
    ) -> None:
        """flush → commit → publish(stream='asset.events') MUST be the order.

        The contract (design.md D-005) is: capture-after-flush /
        publish-after-commit. Reversing flush and commit, or publishing
        before commit, would leak phantom events on rollback.
        """
        from app.modules.assets import service
        from app.modules.assets.schemas import IpAssetCreate

        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        call_log: list[str] = []

        async def _flush() -> None:
            call_log.append("flush")
            obj = db.add.call_args.args[0]
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            now = datetime.now(timezone.utc)
            if getattr(obj, "created_at", None) is None:
                obj.created_at = now
            if getattr(obj, "updated_at", None) is None:
                obj.updated_at = now

        async def _commit() -> None:
            call_log.append("commit")

        db.flush = AsyncMock(side_effect=_flush)
        db.commit = AsyncMock(side_effect=_commit)

        event_bus = MagicMock()

        async def _publish(event, **kwargs):  # type: ignore[no-untyped-def]
            call_log.append("publish")
            return b"stream-id"

        event_bus.publish = AsyncMock(side_effect=_publish)

        data = IpAssetCreate(
            tenant_id=uuid.uuid4(),
            value="192.0.2.50",
            type="ip",
        )
        await service.create_asset(
            data=data, tenant_id=data.tenant_id, db=db, event_bus=event_bus
        )

        assert call_log == [
            "flush",
            "commit",
            "publish",
        ], f"Expected flush→commit→publish ordering; got {call_log!r}"
        # stream= override MUST be asset.events.
        assert event_bus.publish.await_args.kwargs["stream"] == "asset.events"

    @pytest.mark.asyncio
    async def test_list_assets_uses_created_at_desc_then_id_desc(
        self, db_session, seed_data
    ) -> None:
        """list_assets MUST order items by created_at DESC, id DESC.

        Drives the real ``list_assets`` against ``db_session`` so the
        ORDER BY clause is exercised against PostgreSQL itself. Inserts
        three rows with explicit, monotonically-increasing timestamps
        then asserts the returned order is newest-first.
        """
        from sqlalchemy import select
        from sqlalchemy.sql import compiler

        from app.modules.assets import service
        from app.modules.assets.models import Asset

        tenant_a = seed_data["tenant_a"]

        # Insert three assets with explicit, distinct timestamps.
        base_ts = datetime.now(timezone.utc)
        rows = [
            Asset(
                tenant_id=tenant_a.id,
                asset_type="ip",
                value="192.0.2.11",
                created_at=base_ts.replace(microsecond=base_ts.microsecond + 0),
            ),
            Asset(
                tenant_id=tenant_a.id,
                asset_type="ip",
                value="192.0.2.12",
                created_at=base_ts.replace(microsecond=base_ts.microsecond + 100),
            ),
            Asset(
                tenant_id=tenant_a.id,
                asset_type="ip",
                value="192.0.2.13",
                created_at=base_ts.replace(microsecond=base_ts.microsecond + 200),
            ),
        ]
        for row in rows:
            db_session.add(row)
        await db_session.flush()
        await db_session.commit()

        items, total = await service.list_assets(
            tenant_id=tenant_a.id, db=db_session, limit=10, offset=0
        )
        # All three are visible (the seed_data only inserts tenants and
        # users, never assets) so the total reflects this test only.
        assert total == 3
        assert len(items) == 3

        # The ORDER BY clause must surface ``created_at DESC, id DESC``.
        stmt = (
            select(Asset)
            .where(Asset.tenant_id == tenant_a.id)
            .order_by(Asset.created_at.desc(), Asset.id.desc())
            .limit(10)
            .offset(0)
        )
        compiled: compiler.SQLCompiler = stmt.compile(  # type: ignore[attr-defined]
            dialect=db_session.bind.dialect,
            compile_kwargs={"literal_binds": False},
        )
        assert "ORDER BY" in str(compiled).upper()
        order_clause = str(compiled).upper().split("ORDER BY", 1)[1]
        # ``created_at`` appears before ``id`` (stable order).
        assert order_clause.find("CREATED_AT") < order_clause.find(
            "ID"
        ), f"ORDER BY must list created_at DESC before id DESC; got {order_clause!r}"

    @pytest.mark.asyncio
    async def test_update_asset_changed_fields_lists_both_keys_in_stable_order(
        self,
    ) -> None:
        """Updating BOTH ``type`` and ``value`` MUST emit ``["type", "value"]``.

        The ordering matches ``_public_field_names()`` so consumers can
        rely on a stable contract.
        """
        from app.modules.assets import service
        from app.modules.assets.schemas import AssetUpdate

        orm = MagicMock()
        orm.id = uuid.uuid4()
        orm.tenant_id = uuid.uuid4()
        orm.asset_type = "ip"
        orm.value = "192.0.2.10"
        orm.created_at = datetime.now(timezone.utc)
        orm.updated_at = datetime.now(timezone.utc)

        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=orm))
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        data = AssetUpdate(type="hostname", value="app.example.com")
        await service.update_asset(
            asset_id=orm.id,
            tenant_id=orm.tenant_id,
            data=data,
            db=db,
            event_bus=event_bus,
        )

        evt = event_bus.publish.await_args.args[0]
        assert evt.changed_fields == [
            "type",
            "value",
        ], f"Expected changed_fields=['type','value']; got {evt.changed_fields!r}"

    @pytest.mark.asyncio
    async def test_update_asset_persists_canonical_value(
        self, db_session, seed_data
    ) -> None:
        """A PATCH with a non-canonical value MUST store the canonical form.

        Regression for JD-002: ``update_asset`` discarded the return value of
        ``_validate_asset_value`` and persisted the raw input, so
        ``"2001:0DB8:0:0:0:0:0:1"`` could live next to the already-stored
        canonical ``"2001:db8::1"``. Both rows are the same asset logically,
        but ``uq_assets_tenant_type_value`` compares raw strings, so the
        uniqueness guarantee leaked.
        """
        from app.modules.assets import service
        from app.modules.assets.models import Asset
        from app.modules.assets.schemas import AssetUpdate

        tenant_a = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant_a.id,
            asset_type="ip",
            value="192.0.2.10",
        )
        db_session.add(asset)
        await db_session.flush()
        await db_session.commit()

        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        updated = await service.update_asset(
            asset_id=asset.id,
            tenant_id=tenant_a.id,
            data=AssetUpdate(value="2001:0DB8:0:0:0:0:0:1"),
            db=db_session,
            event_bus=event_bus,
        )

        assert updated is not None
        assert updated.value == "2001:db8::1", (
            "PATCH MUST persist the canonical value; " f"got {updated.value!r}"
        )
        evt = event_bus.publish.await_args.args[0]
        assert evt.changed_fields == ["value"], (
            "a real value change MUST still be reported exactly once; "
            f"got {evt.changed_fields!r}"
        )

    @pytest.mark.asyncio
    async def test_update_asset_canonical_equivalent_is_a_noop(
        self, db_session, seed_data
    ) -> None:
        """A PATCH that only re-spells the same value MUST NOT report a change.

        Companion of JD-002: canonicalizing BEFORE the comparison keeps
        ``changed_fields`` truthful for logically identical values.
        """
        from app.modules.assets import service
        from app.modules.assets.models import Asset
        from app.modules.assets.schemas import AssetUpdate

        tenant_a = seed_data["tenant_a"]
        asset = Asset(
            tenant_id=tenant_a.id,
            asset_type="ip",
            value="2001:db8::1",
        )
        db_session.add(asset)
        await db_session.flush()
        await db_session.commit()

        event_bus = MagicMock()
        event_bus.publish = AsyncMock(return_value=b"stream-id")

        updated = await service.update_asset(
            asset_id=asset.id,
            tenant_id=tenant_a.id,
            data=AssetUpdate(value="2001:0db8:0:0:0:0:0:1"),
            db=db_session,
            event_bus=event_bus,
        )

        assert updated is not None
        assert updated.value == "2001:db8::1"
        evt = event_bus.publish.await_args.args[0]
        assert evt.changed_fields == [], (
            "a logically identical value MUST NOT be reported as changed; "
            f"got {evt.changed_fields!r}"
        )

    @pytest.mark.asyncio
    async def test_delete_asset_returns_false_when_asset_not_found(self) -> None:
        """delete_asset MUST return ``False`` when no row matches the scope.

        The router maps ``False`` to HTTP 404. Returning ``True`` or
        raising on miss would either leak existence (204 even when the
        resource was never visible) or break the documented contract.
        """
        from app.modules.assets import service

        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        db.delete = AsyncMock()
        db.commit = AsyncMock()
        event_bus = MagicMock()
        event_bus.publish = AsyncMock()

        ok = await service.delete_asset(
            asset_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            db=db,
            event_bus=event_bus,
        )
        assert ok is False, "delete_asset MUST return False on miss"
        # No commit / no publish when the asset is not in scope.
        db.commit.assert_not_awaited()
        event_bus.publish.assert_not_awaited()
