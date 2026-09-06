"""RED tests for Slice 1 — Assets migration.

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
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import asyncpg
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Isolated test DB used only by the online behavior tests in this module.
# Created/dropped at module scope so we never disturb the shared test DB
# brought to HEAD by the session-scoped `prepare_database` fixture.
ISOLATED_DB = "soc360_test_assets_mig"
ISOLATED_DB_URL = (
    "postgresql+asyncpg://soc360_migration:***REMOVED***"
    f"@localhost:5432/{ISOLATED_DB}"
)


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


def _current_head() -> str:
    """Return the current alembic head revision id."""
    result = _alembic("heads")
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic heads failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    for line in result.stdout.splitlines():
        # Lines look like: 'a1b2c3d4e5f6 (head)'
        m = re.match(r"^([0-9a-f]+)\s+\(head\)", line)
        if m:
            return m.group(1)
    raise RuntimeError(f"No head found in:\n{result.stdout}")


def _previous_head(current_head: str) -> str:
    """Return the parent of `current_head` via `alembic show`."""
    result = _alembic("show", current_head)
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic show {current_head} failed:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    m = re.search(r"^Parent:\s*(\S+)\s*$", result.stdout, re.MULTILINE)
    if m is None:
        raise RuntimeError(
            f"No 'Parent:' line in alembic show output for {current_head}:\n"
            f"{result.stdout}"
        )
    parent = m.group(1).strip()
    if parent.lower() in {"none", "(none)"}:
        raise RuntimeError(
            f"Revision {current_head} has no parent — cannot compute chain."
        )
    return parent


@pytest.fixture(scope="module")
def migration_chain() -> tuple[str, str]:
    """Return (parent_head, current_head) of the migration chain."""
    head = _current_head()
    parent = _previous_head(head)
    return parent, head


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

    def test_uq_assets_tenant_type_value_added(
        self, new_revision_sql: str
    ) -> None:
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
        assert re.search(pattern, new_revision_downgrade_sql, re.IGNORECASE), (
            "Downgrade must drop uq_assets_tenant_type_value."
        )

    def test_downgrade_renames_value_to_name(
        self, new_revision_downgrade_sql: str
    ) -> None:
        pattern = r"alter table\s+assets\s+rename\s+\"?value\"?\s+to\s+\"?name\"?"
        assert re.search(pattern, new_revision_downgrade_sql, re.IGNORECASE), (
            "Downgrade must rename value → name."
        )

    def test_downgrade_readds_hostname_column(
        self, new_revision_downgrade_sql: str
    ) -> None:
        # ALTER TABLE assets ADD COLUMN hostname varchar(255)
        pattern = (
            r"alter table\s+assets\s+add column\s+\"?hostname\"?\s+"
            r"(?:character varying|varchar)"
        )
        assert re.search(pattern, new_revision_downgrade_sql, re.IGNORECASE), (
            "Downgrade must re-add the hostname column as nullable varchar(255)."
        )
        # And nullable (no NOT NULL after the type).
        m = re.search(
            r"alter table\s+assets\s+add column\s+\"?hostname\"?\s+"
            r"(?:character varying|varchar)\s*(?:\(\d+\))?\s*([^,;]*)",
            new_revision_downgrade_sql,
            re.IGNORECASE,
        )
        assert m is not None
        assert "not null" not in m.group(1).lower(), (
            "hostname column in downgrade must be nullable."
        )

    def test_downgrade_maps_hostname_back_to_host(
        self, new_revision_downgrade_sql: str
    ) -> None:
        pattern = (
            r"update\s+assets\s+set\s+asset_type\s*=\s*'host'"
            r"\s+where\s+asset_type\s*=\s*'hostname'"
        )
        assert re.search(pattern, new_revision_downgrade_sql, re.IGNORECASE), (
            "Downgrade must UPDATE asset_type='hostname' back to 'host'."
        )


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
    return (
        result.returncode != 0
        and ("RuntimeError" in result.stderr or "RuntimeError" in result.stdout)
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
            user=user, password=password,
            host=host, port=int(port), database=dbname,
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
            user=user, password=password,
            host=host, port=int(port), database=dbname,
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
            user=admin_user, password=admin_password or None,
            host=host, port=int(port), database="postgres",
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
            user=admin_user, password=admin_password or None,
            host=host, port=int(port), database=dbname,
        )
        try:
            await owner.execute("GRANT ALL ON SCHEMA public TO soc360_migration")
            await owner.execute("GRANT CREATE ON SCHEMA public TO soc360_migration")
        finally:
            await owner.close()

    async def _teardown() -> None:
        admin = await asyncpg.connect(
            user=admin_user, password=admin_password or None,
            host=host, port=int(port), database="postgres",
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
                password="***REMOVED***",
                host="localhost", port=5432, database=ISOLATED_DB,
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
                password="***REMOVED***",
                host="localhost", port=5432, database=ISOLATED_DB,
            )
            try:
                tenant_id = "11111111-1111-1111-1111-111111111111"
                await conn.execute(
                    "INSERT INTO tenants (id, name, slug, plan, is_active, max_assets) "
                    "VALUES ($1, $2, $3, $4, true, 50) "
                    "ON CONFLICT (id) DO NOTHING",
                    tenant_id, "Empresa Alpha", "empresa-alpha", "starter",
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
        assert uq_count == 0, (
            "uq_assets_tenant_type_value must NOT exist after a failed upgrade."
        )

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
                password="***REMOVED***",
                host="localhost", port=5432, database=ISOLATED_DB,
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
                    ("00000000-0000-0000-0000-0000000000a1", tenant_id, "host-1", "host", "active"),
                    ("00000000-0000-0000-0000-0000000000a2", tenant_id, "example.com", "domain", "active"),
                    ("00000000-0000-0000-0000-0000000000a3", tenant_id, "1.2.3.4", "ip", "active"),
                    ("00000000-0000-0000-0000-0000000000a4", tenant_id, "https://app.example.com", "web_app", "active"),
                ]
                for asset_id, tid, name, asset_type, status in rows:
                    await conn.execute(
                        "INSERT INTO assets (id, tenant_id, name, asset_type, status) "
                        "VALUES ($1, $2, $3, $4, $5)",
                        asset_id, tid, name, asset_type, status,
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
        assert name_count == 0, f"name column must be renamed to value; name_count={name_count}"
        assert hostname_count == 0, f"hostname column must be dropped; hostname_count={hostname_count}"
        assert value_count == 1, f"value column must exist after upgrade; value_count={value_count}"

        # Existing rows preserved with values populated.
        rows = asyncio.run(_fetch_all_assets(ISOLATED_DB_URL))
        by_value = {row["value"]: row for row in rows}
        assert "host-1" in by_value, "Row previously named 'host-1' must be in 'value' column."
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
        assert _check_value_count(ISOLATED_DB_URL, uq_sql) == 1, (
            "uq_assets_tenant_type_value must exist after successful upgrade."
        )

        # Six-value check present.
        chk_def = _fetch_scalar(
            ISOLATED_DB_URL,
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
        ) or ""
        for token in ("hostname", "domain", "ip", "web_app", "subnet", "cloud_resource"):
            assert token in chk_def, f"chk_assets_asset_type missing {token!r}: {chk_def!r}"


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
                password="***REMOVED***",
                host="localhost", port=5432, database=ISOLATED_DB,
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
            f"RuntimeError message must mention subnet/cloud_resource. "
            f"Got: {msg!r}"
        )

        # Schema must remain in post-upgrade state.
        chk_def = _fetch_scalar(
            ISOLATED_DB_URL,
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
        ) or ""
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
        assert name_count == 0, f"name must NOT exist (still 'value'); got count={name_count}"
        assert value_count == 1, f"value column must still exist; got count={value_count}"
        assert hostname_count == 0, f"hostname must NOT exist after failed downgrade; got count={hostname_count}"

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
        assert new_types_count == 0, (
            f"Setup: no subnet/cloud_resource rows expected; got {new_types_count}."
        )

        # Downgrade -1 should succeed.
        result = _run_alembic_in_isolated("downgrade", "-1")
        assert result.returncode == 0, (
            f"alembic downgrade -1 must succeed when no subnet/cloud_resource "
            f"rows exist.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Verify post-downgrade shape.
        chk_def = _fetch_scalar(
            ISOLATED_DB_URL,
            "SELECT pg_get_constraintdef(c.oid) "
            "FROM pg_constraint c "
            "JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relname = 'assets' AND c.conname = 'chk_assets_asset_type'",
        ) or ""
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
        assert name_count == 1, f"After downgrade, 'name' must be back; got count={name_count}"
        assert value_count == 0, f"After downgrade, 'value' must be gone; got count={value_count}"
        assert hostname_count == 1, f"After downgrade, 'hostname' must be back; got count={hostname_count}"

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
            user=user, password=password,
            host=host, port=int(port), database=dbname,
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