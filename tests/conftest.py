from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from pathlib import Path

import bcrypt
import pytest
import pytest_asyncio
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

os.environ.setdefault("ENVIRONMENT", "development")

_ENV_FILE = Path(__file__).resolve().parent / ".env"


def _load_env_file(path: Path) -> None:
    """Load KEY=VALUE pairs from a dotenv-style file (dependency-free).

    Blank lines and ``#`` comments are ignored; surrounding quotes are
    stripped. Values are applied via ``os.environ.setdefault`` so variables
    already present in the environment always win. Secret values are never
    printed or logged.
    """
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


_load_env_file(_ENV_FILE)

# Fail closed: secret-bearing settings are required to run the suite.
_MISSING_SECRET_VARS = (
    "DATABASE_URL",
    "DATABASE_URL_MIGRATION",
    "SECRET_KEY",
    "GROQ_API_KEY",
    "POSTGRES_PASSWORD",
)
_missing = [name for name in _MISSING_SECRET_VARS if not os.environ.get(name)]
if _missing:
    raise RuntimeError(
        "Missing required test environment variables: "
        + ", ".join(_missing)
        + ". Copy tests/.env.example to tests/.env and fill in the real "
        "values (tests/.env is gitignored; never commit real values)."
    )

os.environ.setdefault("POSTGRES_USER", "soc360_app")
os.environ.setdefault("POSTGRES_DB", "soc360_test")
# ---------------------------------------------------------------------------
# Redis logical-DB isolation (XD-01)
# ---------------------------------------------------------------------------
# Redis defaults to 16 logical databases (0..15). db=14 is reserved for the
# serial ``tenant_client`` real-Redis fixture and db=15 for the serial
# app pool / Toxiproxy flush target (the Toxiproxy fixtures are serial-only:
# see ``_assert_serial_toxiproxy``), and db=0 is reserved/avoided because of
# ad-hoc dev traffic on db=0, so only indices 1..13 are assignable to xdist
# workers (worker indices 0..12, shifted by +1 so no worker ever lands on
# db=0); anything else is rejected instead of silently colliding.
# Under xdist the app settings pool and the tenant_client real client
# intentionally share ONE worker-specific DB: both run in the same worker
# process and the fixture teardown flushes only that DB.
_XDIST_WORKER_REDIS_DB_LIMIT = 13  # exclusive upper bound on worker index: 0..12 (db 1..13)
_SERIAL_TENANT_REDIS_DB = 14
_SERIAL_APP_REDIS_DB = 15


def _xdist_worker_id() -> str:
    """Return e.g. 'gw0', 'gw1', or '' when not running under pytest-xdist."""
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    return worker if worker and worker != "master" else ""


def _worker_scoped_redis_db(worker_id: str) -> int:
    """Map an xdist worker id to its dedicated Redis logical database.

    Serial runs keep the app-pool default (db=15); every xdist worker gets
    db=<worker index + 1> (gw0->1, gw1->2, ...), shifted by one so no worker
    ever lands on db=0 (reserved for ad-hoc dev traffic), and bounded so no
    worker can land on the reserved serial databases (14/15) either.
    Unsupported worker ids are rejected with an explicit error instead of
    silently colliding with another worker's state.
    """
    if not worker_id:
        return _SERIAL_APP_REDIS_DB
    match = re.fullmatch(r"gw(\d+)", worker_id)
    if not match:
        raise RuntimeError(
            f"Unsupported pytest-xdist worker id {worker_id!r}: cannot "
            "derive a Redis logical database (expected 'gw<index>')."
        )
    index = int(match.group(1))
    if index >= _XDIST_WORKER_REDIS_DB_LIMIT:
        raise RuntimeError(
            f"pytest-xdist worker {worker_id!r} cannot be assigned a Redis "
            f"logical database: index {index} exceeds the assignable range "
            f"0..{_XDIST_WORKER_REDIS_DB_LIMIT - 1} (worker indices map to "
            f"databases 1..{_XDIST_WORKER_REDIS_DB_LIMIT}; db=0 is reserved "
            "for ad-hoc dev traffic, and databases "
            f"{_SERIAL_TENANT_REDIS_DB} and {_SERIAL_APP_REDIS_DB} are "
            "reserved for the serial tenant_client and Toxiproxy fixtures). "
            f"Run with -n {_XDIST_WORKER_REDIS_DB_LIMIT} or fewer workers."
        )
    return index + 1


def redis_db_value() -> int:
    """Resolve the Redis logical DB for this process.

    Serial runs honor an explicit ``REDIS_DB``; with none set they default
    to db=15. Under pytest-xdist the worker mapping always wins, even when
    ``REDIS_DB`` is exported (e.g. CI sets ``REDIS_DB=15``, the serial
    Toxiproxy/app-pool target): honoring it would put every worker on the
    same shared logical DB. This must run before any ``app.core`` import
    so ``app.core.config.settings`` and the app's shared connection pool
    bind to this worker's own logical DB.
    """
    worker_id = _xdist_worker_id()
    if worker_id:
        return _worker_scoped_redis_db(worker_id)
    env_value = os.environ.get("REDIS_DB")
    if env_value is not None:
        return int(env_value)
    return _worker_scoped_redis_db(worker_id)


def _tenant_client_redis_db(worker_id: str) -> int:
    """Redis DB for the ``tenant_client`` real-Redis fixture.

    Serial runs keep the historical db=14 (isolated from the app pool's
    db=15 and from ad-hoc dev traffic on db=0). Under xdist the fixture
    shares the app pool's worker-specific DB (db=<worker index + 1>, never
    db=0): both run in the same worker process, so a per-worker DB isolates
    them from other workers, while the per-test flushdb teardown shows the
    app pool exactly the serial behavior it already expects.
    """
    if not worker_id:
        return _SERIAL_TENANT_REDIS_DB
    return _worker_scoped_redis_db(worker_id)


# Structured Redis settings (PR1 #260 — REDIS_URL is rejected)
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
# Worker-specific Redis logical DB (XD-01): resolved (and pinned into the
# environment) BEFORE any app.core import so settings REDIS_DB and the
# app's shared connection pool bind to this worker's own logical DB.
# Serial runs keep ``setdefault`` semantics: an explicit REDIS_DB wins.
# Under xdist the worker mapping is authoritative and OVERWRITES the
# environment, because CI exports REDIS_DB=15 and both workers would
# otherwise bind the same shared db=15.
_resolved_redis_db = redis_db_value()
if _xdist_worker_id():
    os.environ["REDIS_DB"] = str(_resolved_redis_db)
else:
    os.environ.setdefault("REDIS_DB", str(_resolved_redis_db))
os.environ.setdefault("REDIS_PASSWORD", "soc360_redis_dev_password")
# PR5b' distributed lock secret (must be at least 32 bytes to satisfy production
# validation in app/core/config.py; this default is test-only).
os.environ.setdefault(
    "LOCK_KEY_SECRET",
    "ci-test-lock-secret-key-32bytes-min-do-not-use-in-prod",
)

from app.core.redis import close_pool, get_redis
from app.dependencies import get_db, get_db_with_tenant
from app.main import create_app
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

TENANT_A_ID = "11111111-1111-1111-1111-111111111111"
TENANT_B_ID = "22222222-2222-2222-2222-222222222222"
SUPERADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ADMIN_A_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ANALYST_A_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
VIEWER_A_ID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
ADMIN_B_ID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
# Slice 1 (F2): ``ingestor`` is one of the five canonical F1 roles and is
# explicitly DENIED on every Assets endpoint (D-006 / RBAC matrix). The
# tests/conftest seed_data fixture inserts an ingestor user bound to
# TENANT_A so the T11.2 RBAC matrix can verify the 403 cases.
INGESTOR_A_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")

# Arbitrary advisory-lock key used only to serialize one-time, cluster-wide
# test bootstrap steps (CREATE DATABASE, CREATE/ALTER ROLE) across
# concurrent pytest-xdist workers. Distinct from the per-user_id keys the
# app itself uses for pg_advisory_xact_lock in app/modules/auth/service.py.
# Advisory locks are scoped per-database, not truly cluster-wide, so this
# only serializes workers because every one of them takes it through a
# connection to the same 'postgres' maintenance database (see
# _maintenance_connection) — never move that lock onto a worker's own
# database, or cross-worker serialization silently stops working.
_XDIST_BOOTSTRAP_LOCK_KEY = 727271001


def _worker_scoped_db_url(url: str, worker_id: str) -> str:
    """Append the xdist worker id to the URL's database name.

    Every pytest-xdist worker is a separate process running the full suite
    against the SAME Postgres instance. Without a distinct database per
    worker, two workers would concurrently ``alembic downgrade base`` /
    ``upgrade head`` the same physical database, corrupting each other's
    schema and data mid-test-run.
    """
    if not worker_id:
        return url
    parsed = make_url(url)
    if not parsed.database or not _SAFE_IDENTIFIER.match(worker_id):
        raise RuntimeError(
            "Cannot derive a worker-scoped database name from "
            f"{parsed.render_as_string(hide_password=True)!r} and worker id "
            f"{worker_id!r}."
        )
    # render_as_string(hide_password=False) is required: str(url) masks the
    # password as "***" by default, which would silently break every
    # connection made with this worker-scoped URL.
    return parsed.set(database=f"{parsed.database}_{worker_id}").render_as_string(
        hide_password=False
    )


_XDIST_WORKER_ID = _xdist_worker_id()
TEST_DATABASE_URL = _worker_scoped_db_url(os.environ["DATABASE_URL"], _XDIST_WORKER_ID)
MIGRATION_DATABASE_URL = _worker_scoped_db_url(
    os.environ["DATABASE_URL_MIGRATION"], _XDIST_WORKER_ID
)
# Only MIGRATION_DATABASE_URL's database is ever CREATE DATABASE'd (see
# _ensure_database_exists below) — this assumes DATABASE_URL and
# DATABASE_URL_MIGRATION name the SAME database (just different roles
# connecting to it). If that ever stops being true, the app-role's
# database silently never gets created under xdist. Only checked under
# xdist, where CREATE DATABASE actually runs — a plain `assert` would also
# be stripped under `python -O`, and running it unconditionally would
# break single-process setups that never needed the two URLs to agree.
if _XDIST_WORKER_ID and (
    make_url(TEST_DATABASE_URL).database != make_url(MIGRATION_DATABASE_URL).database
):
    raise RuntimeError(
        "DATABASE_URL and DATABASE_URL_MIGRATION must point at the same "
        "database name for pytest-xdist's per-worker database creation to work"
    )


async def _acquire_bootstrap_lock(conn, timeout_seconds: float = 60.0) -> None:
    """Bounded-wait acquire of the xdist bootstrap advisory lock.

    A plain ``pg_advisory_lock()`` blocks indefinitely with no timeout
    option of its own (``lock_timeout`` does not apply to it). Polling
    ``pg_try_advisory_lock`` instead means a wedged worker (crashed mid
    bootstrap, connection stuck) produces a clear timeout error instead of
    hanging every other worker — and the whole CI job — until the outer
    job timeout kills it.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        acquired = await conn.fetchval(
            f"SELECT pg_try_advisory_lock({_XDIST_BOOTSTRAP_LOCK_KEY})"
        )
        if acquired:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out after {timeout_seconds}s waiting for the xdist "
                "bootstrap advisory lock — another worker's setup may be stuck."
            )
        await asyncio.sleep(0.2)


async def _maintenance_connection():
    """Open an asyncpg connection to the ``postgres`` maintenance database.

    Uses the migration role's credentials. Needed for anything that can't
    target a possibly-not-yet-existing worker database — CREATE DATABASE,
    and the xdist bootstrap advisory lock, which must be held on a
    connection that outlives and is independent of that worker database.
    """
    import asyncpg

    admin_url = make_url(MIGRATION_DATABASE_URL)
    return await asyncpg.connect(
        user=admin_url.username,
        password=admin_url.password,
        host=admin_url.host,
        port=admin_url.port,
        database="postgres",
    )


async def _ensure_database_exists(conn, dbname: str) -> None:
    """``CREATE DATABASE`` if it doesn't exist yet (idempotent, per worker).

    Takes an already-open maintenance-DB connection (see
    ``_maintenance_connection``) — Postgres forbids ``CREATE DATABASE``
    inside a transaction block, and the target database itself may not
    exist yet, so no other connection target works here.
    """
    if not _SAFE_IDENTIFIER.match(dbname):
        raise RuntimeError(f"Refusing to create database with unsafe name: {dbname!r}")

    exists = await conn.fetchval(
        "SELECT 1 FROM pg_database WHERE datname = $1", dbname
    )
    if not exists:
        await conn.execute(f'CREATE DATABASE "{dbname}"')


async def _ensure_app_role() -> None:
    """Idempotently create the soc360_app login role for test GRANTs.

    The role is created outside the schema transaction via a raw asyncpg
    connection to avoid any transactional-DDL edge cases with CREATE ROLE.
    Safe for repeated test runs (DO $$ IF NOT EXISTS).
    """
    import asyncpg

    parsed = make_url(MIGRATION_DATABASE_URL)
    if (
        not parsed.username
        or not parsed.password
        or not parsed.host
        or not parsed.port
        or not parsed.database
    ):
        raise RuntimeError(
            f"MIGRATION_DATABASE_URL is incomplete: missing one or more "
            f"required URL components (user, password, host, port, database). "
            f"Got: host={parsed.host}, port={parsed.port}, database={parsed.database}"
        )
    conn = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
    )
    # Extract the password for soc360_app from the test DATABASE_URL
    # so _ensure_app_role and db_session use the same credential.
    app_parsed = make_url(TEST_DATABASE_URL)
    app_password = app_parsed.password
    if not app_password:
        raise RuntimeError(
            "TEST_DATABASE_URL is missing its password component; "
            "set DATABASE_URL in tests/.env"
        )
    try:
        role_exists = await conn.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'soc360_app'"
        )
        action = "ALTER" if role_exists else "CREATE"
        # Postgres does not accept $-parameters in ALTER/CREATE ROLE's
        # PASSWORD clause (confirmed: raises a syntax error), so this
        # can't be parameter-bound like a normal query. Double up any
        # single quotes instead — the standard SQL string-literal
        # escape, safe for arbitrary content unlike a fixed dollar-quote
        # delimiter (which a password could coincidentally contain).
        escaped_password = app_password.replace("'", "''")
        await conn.execute(
            f"{action} ROLE soc360_app WITH LOGIN PASSWORD "
            f"'{escaped_password}' NOSUPERUSER NOBYPASSRLS"
        )
    finally:
        await conn.close()


async def _bootstrap_worker_database() -> None:
    """Create this worker's database and app role (idempotent, locked).

    Serializes only the steps that touch Postgres's cluster-wide shared
    catalogs (pg_database for CREATE DATABASE, pg_authid for CREATE/ALTER
    ROLE) — concurrent workers running these can fail with "tuple
    concurrently updated" on those catalogs. Migrations that follow target
    each worker's own, already-isolated database, so they do NOT need the
    lock; holding it that long would serialize every worker's full
    migration cycle, and a fixed lock-wait timeout would then have to scale
    with the worker count. Shared by the root and integration
    ``prepare_database`` fixtures under xdist.
    """
    lock_conn = await _maintenance_connection()
    try:
        await _acquire_bootstrap_lock(lock_conn)
        try:
            await _ensure_database_exists(
                lock_conn, make_url(MIGRATION_DATABASE_URL).database
            )
            await _ensure_app_role()
        finally:
            # Best-effort: if the connection itself is what broke (e.g. the
            # server restarted mid-bootstrap), this unlock call would also
            # fail and its error would replace — and hide — the real
            # exception above. Postgres releases session advisory locks
            # automatically when the connection closes (see the outer
            # finally), so this is a courtesy, not the only way the lock
            # gets released.
            try:
                await lock_conn.execute(
                    f"SELECT pg_advisory_unlock({_XDIST_BOOTSTRAP_LOCK_KEY})"
                )
            except Exception:
                pass
    finally:
        await lock_conn.close()


def _assert_safe_test_database() -> None:
    """Fail closed before any destructive migration reset.

    Guards against a misconfigured MIGRATION_DATABASE_URL wiping a real
    database: the environment must not be production/staging and the target
    DB name must look like a test database.
    """
    env = os.environ.get("ENVIRONMENT", "").lower()
    if env in {"production", "prod", "staging"}:
        raise RuntimeError(f"Refusing destructive DB reset in ENVIRONMENT={env!r}")
    db_name = (make_url(MIGRATION_DATABASE_URL).database or "").lower()
    if "test" not in db_name:
        raise RuntimeError(
            f"Refusing 'alembic downgrade base': database {db_name!r} does not "
            "look like a test database (name must contain 'test')."
        )


def _seed_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _run_alembic(*args: str) -> None:
    """Run alembic command with MIGRATION_DATABASE_URL env."""
    env = {
        **os.environ,
        "DATABASE_URL_MIGRATION": MIGRATION_DATABASE_URL,
    }
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic {' '.join(args)} failed:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )


# ✅ SYNC fixture — usa asyncio.run() para no contaminar ningún loop de test
@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    def _run_migrations() -> None:
        # Drop everything and re-run the full Alembic chain so RLS
        # policies, GRANTs, triggers, and indexes are created exactly as
        # in production. Shared by both the single-process and xdist
        # paths below so they can't silently drift apart.
        _run_alembic("downgrade", "base")
        _run_alembic("upgrade", "head")

    async def _setup() -> None:
        _assert_safe_test_database()

        if not _XDIST_WORKER_ID:
            # Single-process run: no other worker to race against, so skip
            # the maintenance-DB connection and lock entirely. This keeps
            # the exact pre-xdist behavior — in particular, it does not
            # newly require the migration role to have CONNECT on the
            # 'postgres' maintenance database, which some managed/hardened
            # Postgres setups restrict.
            await _ensure_app_role()
            _run_migrations()
            return

        await _bootstrap_worker_database()
        # Runs unlocked, in parallel across workers — see _run_migrations.
        _run_migrations()

    async def _teardown() -> None:
        _assert_safe_test_database()
        _run_alembic("downgrade", "base")

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with engine.connect() as connection:
        # Outer transaction — rolled back on fixture teardown so app-level
        # commits (e.g. lock_deps.db.commit()) cannot leak state between tests.
        transaction = await connection.begin()
        # Session bound to the connection with savepoint join mode: every
        # application commit releases the current savepoint instead of
        # committing the outer transaction, so the fixture's outer rollback
        # below reverts every change the test made.
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    from uuid import UUID

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Idempotent tenant inserts — concurrency tests may have already committed these
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    await db_session.execute(
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
    await db_session.execute(
        pg_insert(Tenant)
        .values(
            id=UUID(TENANT_B_ID),
            name="Empresa Beta",
            slug="empresa-beta",
            plan="free",
            is_active=True,
            max_assets=10,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()

    # Idempotent user inserts
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(SUPERADMIN_ID),
            tenant_id=None,
            email="superadmin@soc360.test",
            hashed_password=_seed_password_hash("SuperAdmin123!"),
            full_name="Super Admin",
            role="superadmin",
            is_active=True,
            is_superadmin=True,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(ADMIN_A_ID),
            tenant_id=UUID(TENANT_A_ID),
            email="admin@alpha.test",
            hashed_password=_seed_password_hash("AdminAlpha123!"),
            full_name="Admin Alpha",
            role="admin",
            is_active=True,
            is_superadmin=False,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(ANALYST_A_ID),
            tenant_id=UUID(TENANT_A_ID),
            email="analyst@alpha.test",
            hashed_password=_seed_password_hash("AnalystAlpha123!"),
            full_name="Analyst Alpha",
            role="analyst",
            is_active=True,
            is_superadmin=False,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(VIEWER_A_ID),
            tenant_id=UUID(TENANT_A_ID),
            email="viewer@alpha.test",
            hashed_password=_seed_password_hash("ViewerAlpha123!"),
            full_name="Viewer Alpha",
            role="viewer",
            is_active=True,
            is_superadmin=False,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(ADMIN_B_ID),
            tenant_id=UUID(TENANT_B_ID),
            email="admin@beta.test",
            hashed_password=_seed_password_hash("AdminBeta123!"),
            full_name="Admin Beta",
            role="admin",
            is_active=True,
            is_superadmin=False,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    # Ingestor (F1 canonical role) — T11.2 RBAC matrix requires a
    # user with role='ingestor' to exercise the six 403 denials on
    # the Assets endpoints (D-006).
    await db_session.execute(
        pg_insert(User)
        .values(
            id=UUID(INGESTOR_A_ID),
            tenant_id=UUID(TENANT_A_ID),
            email="ingestor@soc360.test",
            hashed_password=_seed_password_hash("IngestorAlpha123!"),
            full_name="Ingestor Alpha",
            role="ingestor",
            is_active=True,
            is_superadmin=False,
        )
        .on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()

    # Fetch persisted records for test use
    tenant_a = await db_session.get(Tenant, UUID(TENANT_A_ID))
    tenant_b = await db_session.get(Tenant, UUID(TENANT_B_ID))
    superadmin = await db_session.get(User, UUID(SUPERADMIN_ID))
    admin_a = await db_session.get(User, UUID(ADMIN_A_ID))
    analyst_a = await db_session.get(User, UUID(ANALYST_A_ID))
    viewer_a = await db_session.get(User, UUID(VIEWER_A_ID))
    admin_b = await db_session.get(User, UUID(ADMIN_B_ID))
    ingestor_a = await db_session.get(User, UUID(INGESTOR_A_ID))

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "superadmin": superadmin,
        "admin_a": admin_a,
        "analyst_a": analyst_a,
        "viewer_a": viewer_a,
        "admin_b": admin_b,
        "ingestor_a": ingestor_a,
    }


class _LuaCapableFakeRedis(FakeRedis):
    """FakeRedis subclass that implements ``EVAL`` for the lock release/renew scripts.

    Plain ``fakeredis==2.34.1`` (without the ``lupa`` extra) rejects ``EVAL`` with
    ``ResponseError: unknown command 'eval'``. The distributed-lock module uses
    two owner-checked Lua scripts (``RENEW_LUA``, ``RELEASE_LUA``) for safe release
    and renew under contention; tests that drive the deactivation routes through
    the public ``client`` fixture would otherwise return 503 because the lock
    release fails. This adapter implements the same semantics directly against
    the in-memory store so the full lock lifecycle is exercised.

    Only the two scripts emitted by ``app.core.dist_lock`` are supported — adding
    a third would require re-evaluating this adapter.
    """

    async def eval(self, script, numkeys, *args):  # type: ignore[override]
        if numkeys != 1:
            raise NotImplementedError(
                f"_LuaCapableFakeRedis only supports 1-key scripts, got {numkeys}"
            )
        key, token, argument = args
        current = await self.get(key)
        if isinstance(current, bytes):
            current = current.decode()
        if current != token:
            return 0
        if "PEXPIRE" in script:
            return int(await self.pexpire(key, int(argument)))
        # DEL (release)
        return int(await self.delete(key))


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    from app.dependencies import event_deps as _event_deps
    from app.dependencies.event_deps import get_event_bus
    from app.event_bus import EventBus as _FakeEventBus

    app = create_app()
    fake_redis = _LuaCapableFakeRedis(
        decode_responses=True
    )  # ✅ mismo loop que el test (function scope)

    async def override_get_db():
        yield db_session

    async def override_get_db_with_tenant():
        yield db_session

    async def override_get_redis():
        yield fake_redis

    # The auth login flow publishes ``auth.login`` events on
    # ``get_event_bus``. Without an override, the default
    # ``app.dependencies.event_deps.get_event_bus`` materialises a
    # singleton against the settings pool (db=15 + password). On the
    # local dev Redis that AUTH-fails and caches a poisoned bus that
    # leaks into ``tenant_client``'s test body, crashing asset
    # publishes with ``RedisUnreachableError`` -> 503. The override
    # pins the bus to the same FakeRedis the fixture already uses,
    # which supports the basic rate-limit / incr / expire calls the
    # auth flow actually issues.
    async def override_get_event_bus():
        if _event_deps._event_bus is None:
            _event_deps._event_bus = _FakeEventBus(fake_redis)
        return _event_deps._event_bus

    # The auth service does NOT route ``get_event_bus`` through FastAPI
    # DI — ``app.modules.auth.service.login`` calls its own local
    # ``get_event_bus`` wrapper directly. Patch that wrapper in-place so
    # the auth login publishes to the FakeRedis-backed bus instead of
    # materialising a singleton against the default settings pool
    # (db=15 + password). Otherwise the auth login caches a poisoned
    # bus on ``app.dependencies.event_deps._event_bus`` that leaks into
    # ``tenant_client``'s test body and crashes asset publishes with
    # ``RedisUnreachableError`` -> 503.
    import app.modules.auth.service as _auth_service

    # Capture the pristine wrapper so the in-place patch below can be undone
    # at teardown: leaving it patched leaks a FakeRedis-backed bus into every
    # later fixture that resolves the real ``get_event_bus``.
    _original_auth_get_event_bus = _auth_service.get_event_bus

    async def _auth_get_event_bus() -> _FakeEventBus:
        return await override_get_event_bus()

    _auth_service.get_event_bus = _auth_get_event_bus

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_with_tenant] = override_get_db_with_tenant
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_event_bus] = override_get_event_bus

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac
    finally:
        _auth_service.get_event_bus = _original_auth_get_event_bus


def _redis_client_target(redis_client: object) -> tuple[str, int, int, str | None] | None:
    """Return the ``(host, port, db, password)`` tuple ``redis_client`` is bound to.

    Reads ``connection_pool.connection_kwargs`` — the attribute path a
    ``redis.asyncio.Redis`` client (``redis==5.2.1``, pinned in
    ``uv.lock``; see ``app/core/redis.py``'s ``Redis(connection_pool=...)``
    construction) stores its connection target under. Comparing the full
    ``(host, port, db)`` triple (not just the DB index alone) closes a gap
    a Guardian Angel/Codex review caught: two clients pointing at the same
    DB *number* on two different Redis servers are not the same target,
    so matching only the DB index could wrongly trust a bus connected to
    an entirely different Redis instance. This works for *any* real Redis
    client regardless of pool identity: two distinct ``Redis(...)`` calls
    (and therefore two distinct ``ConnectionPool`` objects) targeting the
    same host/port/db still report the same triple here, which is exactly
    what lets a legitimately different real-Redis pool be trusted below.

    ``password`` is included for the same reason: ``tenant_client``
    (below) tries an authenticated connection first and falls back to
    unauthenticated only on ``AuthenticationError``. Two clients can share
    the same ``(host, port, db)`` while one authenticates and the other
    doesn't (e.g. local Redis flips between requiring auth across runs) —
    trusting a cached bus on host/port/db alone would let it reuse the
    WRONG credentials for this client's connection, another Guardian
    Angel/Codex review finding. ``.get("password")`` (not ``[...]``) since
    an unauthenticated client's kwargs may omit the key entirely; that
    absence still participates in the comparison, so an authenticated vs.
    unauthenticated mismatch is never silently trusted.

    Returns ``None`` — rather than raising — for anything that is not a
    real Redis client wired this way (unexpected type, missing attribute,
    or any error while reading it), so callers fail closed and treat the
    target as unknown/untrusted instead of assuming it is safe.
    """
    try:
        kwargs = redis_client.connection_pool.connection_kwargs
        return (kwargs["host"], kwargs["port"], kwargs["db"], kwargs.get("password"))
    except Exception:
        return None


def _rebind_event_bus_if_stale(cached_bus: object, redis_client: object, bus_cls: type):
    """Return an ``EventBus`` safe for ``tenant_client`` to use.

    Rebuilds a fresh ``bus_cls(redis_client)`` when ``cached_bus`` is
    ``None``, bound to a ``FakeRedis`` client, or bound to a real
    ``redis.asyncio.Redis`` client whose ``(host, port, db, password)``
    target does not match ``redis_client``'s; otherwise trusts and reuses
    ``cached_bus`` as-is. This is the fix for a fixture-resolution-order
    hazard: ``event_deps._event_bus = None`` clear points in
    ``tenant_client`` are order-dependent — a fixture resolving a login
    through the ``client`` fixture (e.g. ``admin_a_headers`` ->
    ``admin_a_token`` -> ``client.post('/api/v1/auth/login')``) after the
    last clear point, but before the first request through
    ``tenant_client``'s app, re-caches the singleton against the
    ``client`` fixture's own ``FakeRedis``-backed bus. Checking the cached
    bus's Redis client *type*, and — for a real client — the exact target
    it is actually bound to (rather than its identity against a single
    expected ``redis_client``), targets exactly that hazard without
    discarding a legitimately different real-Redis bus that happens to
    point at the same target.

    ``TestEventsSpy`` in ``tests/api/test_assets.py`` needs to monkeypatch
    ``bus.publish`` on the EXACT instance the route handler will use. It
    does this by resolving the bus through
    ``tenant_client.app.dependency_overrides[get_event_bus]()`` — the same
    ``override_get_event_bus`` closure (and therefore the same call into
    this function) the route handler's dependency injection resolves —
    rather than calling ``event_deps.get_event_bus()`` directly and hoping
    fixture-resolution order happens to hand back the same singleton. That
    guarantees the spy's fetch and the route handler's fetch agree on the
    same, correctly-target-checked instance, so this function needs no
    "trust a monkeypatched bus unconditionally" exception: every bus it
    hands out, spied or not, still goes through the target check below.

    A real ``redis.asyncio.Redis``-backed bus is trusted only when ``_redis_client_target(cached_bus._redis)`` equals
    ``_redis_client_target(redis_client)``: the same ``(host, port, db,
    password)`` tuple, any pool object. A bus bound to a *different* target (e.g.
    one built via a direct, un-instrumented call to
    ``event_deps.get_event_bus()``, which under a serial run defaults to
    ``settings.REDIS_DB`` = db 15 while ``tenant_client`` explicitly uses
    db 14) is no longer blindly trusted just because it is real Redis —
    it is rebuilt against ``redis_client`` instead. This closes the
    Guardian Angel/Codex reviewer finding that this function previously
    trusted "any real Redis-backed bus regardless of DB" (and, in an
    earlier pass, regardless of which Redis *server* even shared that DB
    number), either of which let ``tenant_client`` publish outside its
    assigned worker/tenant database. If the cached bus's target (or
    ``redis_client``'s target) cannot be determined,
    ``_redis_client_target`` returns ``None`` and the mismatch branch
    below fails closed by rebuilding, rather than assuming the bus is
    safe.
    """
    if cached_bus is None:
        return bus_cls(redis_client)
    cached_redis = getattr(cached_bus, "_redis", None)
    if isinstance(cached_redis, FakeRedis):
        return bus_cls(redis_client)
    cached_target = _redis_client_target(cached_redis)
    if cached_target is not None and cached_target == _redis_client_target(redis_client):
        return cached_bus
    return bus_cls(redis_client)


# ---------------------------------------------------------------------------
# Slice 1 (F2) — tenant_client fixture with explicit RLS context
# ---------------------------------------------------------------------------
# Critical: ``httpx.AsyncClient`` + ``ASGITransport`` only act as an HTTP
# transport against the ASGI app; they do NOT establish RLS context nor a
# tenant scope by themselves. The plain ``client`` fixture above only
# overrides ``get_db`` and skips ``set_tenant_context`` (the F1 baseline),
# which would let RLS leak between tests. The ``tenant_client`` fixture
# explicitly wires ``set_tenant_context(db_session, current_user.tenant_id,
# current_user.is_superadmin)`` for the resolved ``current_user`` so the
# RLS predicates (``app.current_tenant`` / ``app.is_superadmin``) match
# the requester's identity at every test boundary.
@pytest_asyncio.fixture
async def tenant_client(db_session: AsyncSession):
    from fastapi import Depends
    from redis.asyncio import Redis as _RealAsyncRedis

    from app.core.config import settings as _settings
    from app.core.database import set_tenant_context
    from app.dependencies.auth import get_current_user
    from app.dependencies.event_deps import get_event_bus
    from app.event_bus import EventBus as _TestEventBus
    from app.modules.users.models import User as _User

    # Force a fresh EventBus singleton for THIS test. The autouse
    # ``_reset_event_bus_singleton`` resets the singleton to ``None``
    # before the test, but if the test transitively pulled in the
    # ``client`` fixture (e.g. ``admin_a_headers`` -> token ->
    # ``client.post('/api/v1/auth/login')``) the auth login already
    # resolved ``get_event_bus`` once and cached a bus pointing at the
    # default settings pool (db=15 + password). On local Redis that bus
    # AUTH-fails, and the cached singleton is then reused by the asset
    # route handlers, which publish ``asset.created/updated/deleted``
    # events on it and crash with ``RedisUnreachableError`` -> 503.
    # Clearing it here lets the override below materialise a fresh bus
    # bound to ``test_redis`` (db=14, no AUTH) before the first asset
    # request runs.
    from app.dependencies import event_deps

    event_deps._event_bus = None

    app = create_app()
    # Slice 1 (F2) requires a real Redis: fakeredis 2.34 does not
    # implement Redis Streams (XADD) reliably, which the asset
    # mutation endpoints exercise via EventBus.publish(stream="asset.events").
    # Use db=14 to isolate from F1's db=15 fixtures and from any
    # ad-hoc dev traffic on db=0. Password comes from the same
    # settings that the production app uses.
    from redis.exceptions import AuthenticationError as _RedisAuthenticationError

    def _build_test_redis(password: str | None) -> _RealAsyncRedis:
        return _RealAsyncRedis(
            host=_settings.REDIS_HOST,
            port=_settings.REDIS_PORT,
            db=_tenant_client_redis_db(_XDIST_WORKER_ID),
            password=password,
            decode_responses=True,
        )

    # CI's redis:7-alpine service is started with --requirepass and expects
    # settings.REDIS_PASSWORD; a bare local Redis (no --requirepass) rejects
    # AUTH entirely. Try authenticated first (matches app.core.redis), then
    # fall back to no password so local dev keeps working unauthenticated.
    redis_password = _settings.REDIS_PASSWORD.get_secret_value() or None
    test_redis = _build_test_redis(redis_password)
    try:
        await test_redis.ping()
    except _RedisAuthenticationError:
        await test_redis.aclose()
        test_redis = _build_test_redis(None)
        try:
            await test_redis.ping()
        except Exception as exc:  # pragma: no cover - env guard
            await test_redis.aclose()
            raise RuntimeError(
                "tenant_client fixture requires a reachable Redis on "
                f"{_settings.REDIS_HOST}:{_settings.REDIS_PORT} "
                f"db={_tenant_client_redis_db(_XDIST_WORKER_ID)}. "
                f"Original error: {exc!r}"
            ) from exc
    except Exception as exc:  # pragma: no cover - env guard
        await test_redis.aclose()
        raise RuntimeError(
            "tenant_client fixture requires a reachable Redis on "
            f"{_settings.REDIS_HOST}:{_settings.REDIS_PORT} "
            f"db={_tenant_client_redis_db(_XDIST_WORKER_ID)}. "
            f"Original error: {exc!r}"
        ) from exc

    async def override_get_db():
        yield db_session

    async def override_get_db_with_tenant(
        user: _User = Depends(get_current_user),
    ):
        # Defence-in-depth: explicitly set RLS context for ``user``
        # before yielding the shared test session. ``get_current_user``
        # itself calls ``set_tenant_context`` during user resolution,
        # so this is idempotent for the same request.
        await set_tenant_context(
            db=db_session,
            tenant_id=user.tenant_id,
            is_superadmin=user.is_superadmin,
        )
        yield db_session

    async def override_get_redis():
        yield test_redis

    # get_event_bus builds its EventBus from get_redis_client()
    # (singleton pool) instead of Depends(get_redis), so the
    # get_redis override alone does NOT steer Events. Reset the
    # module-level singleton to point at test_redis. This keeps a
    # SINGLE bus instance across the request lifecycle so the spy in
    # TestEventsSpy (which obtains the same singleton via
    # event_deps.get_event_bus()) patches the exact instance
    # the asset route uses.
    async def override_get_event_bus():
        from app.dependencies import event_deps

        # Reuse the existing singleton unless it is a leaked, un-instrumented
        # ``FakeRedis``-backed bus. The two ``event_deps._event_bus = None``
        # clear points above are best-effort: if a fixture that transitively
        # depends on ``client`` (e.g. ``admin_a_token`` -> ``client.post``
        # login) resolves AFTER the last clear point but BEFORE the first
        # request through this client's app, it re-caches the singleton
        # against the ``client`` fixture's own ``FakeRedis``-backed bus
        # instead of ``test_redis`` (db=14). Trusting ``is None`` alone is
        # therefore order-dependent and unsound. ``_rebind_event_bus_if_stale``
        # checks the TYPE of the Redis client the cached bus is actually
        # bound to (``EventBus._redis``): a ``FakeRedis``-backed bus is
        # discarded and rebuilt against ``test_redis``. A real
        # ``redis.asyncio.Redis``-backed bus is trusted only when its
        # (host, port, db, password) TARGET
        # (``connection_pool.connection_kwargs``) matches ``test_redis``'s
        # — a different pool object targeting the same host/port/db/
        # password is still trusted, but a real bus bound to a
        # DIFFERENT target (e.g. one built via a direct, un-instrumented
        # ``event_deps.get_event_bus()`` call defaulting to
        # ``settings.REDIS_DB``, or one pointed at a different Redis
        # server entirely) is rebuilt instead of blindly trusted, which
        # would otherwise let this client publish outside its assigned
        # worker/tenant database.
        # ``TestEventsSpy`` (tests/api/test_assets.py) resolves the bus
        # through this exact closure — via
        # ``tenant_client.app.dependency_overrides[get_event_bus]()`` —
        # instead of calling ``event_deps.get_event_bus()`` directly, so
        # it always gets the same, correctly target-checked instance the
        # route handler will use, with no special-casing needed here for
        # an already-monkeypatched bus. Once correctly bound, the same
        # instance is reused across the request lifecycle so
        # TestEventsSpy's monkeypatch of ``bus.publish`` stays attached to
        # the instance the route handler actually uses.
        event_deps._event_bus = _rebind_event_bus_if_stale(
            event_deps._event_bus, test_redis, _TestEventBus
        )
        return event_deps._event_bus

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_with_tenant] = override_get_db_with_tenant
    app.dependency_overrides[get_redis] = override_get_redis
    app.dependency_overrides[get_event_bus] = override_get_event_bus

    # ``tenant_client`` is resolved BEFORE ``admin_a_token`` (pytest
    # resolves fixtures top-down through the dependency graph). The
    # auth login inside ``admin_a_token`` therefore resolves
    # ``get_event_bus`` AFTER this reset, materialising a bus against
    # the default settings pool (db=15 + password). On local Redis
    # that bus AUTH-fails, and the cached singleton is then reused by
    # the asset route handlers, which publish
    # ``asset.created/updated/deleted`` events on it and crash with
    # ``RedisUnreachableError`` -> 503. Re-clear the singleton here
    # so the very first request through this client materialises a
    # bus bound to ``test_redis`` (db=14, no AUTH).
    from app.dependencies import event_deps

    event_deps._event_bus = None

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # Exposed so a test can resolve the EXACT EventBus instance the
            # route handler will use, via
            # ``tenant_client.app.dependency_overrides[get_event_bus]()``
            # (calls ``override_get_event_bus`` above) — instead of calling
            # ``event_deps.get_event_bus()`` directly and relying on
            # fixture-resolution-order luck to land on the same singleton.
            # See ``TestEventsSpy`` in ``tests/api/test_assets.py``.
            ac.app = app
            yield ac
    finally:
        await test_redis.flushdb()
        await test_redis.aclose()


async def _get_token(client: AsyncClient, email: str, password: str) -> str:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login fallo para {email}: {resp.text}"
    return resp.json()["access_token"]


@pytest_asyncio.fixture
async def superadmin_token(client: AsyncClient, seed_data) -> str:
    return await _get_token(client, "superadmin@soc360.test", "SuperAdmin123!")


@pytest_asyncio.fixture
async def admin_a_token(client: AsyncClient, seed_data) -> str:
    return await _get_token(client, "admin@alpha.test", "AdminAlpha123!")


@pytest_asyncio.fixture
async def analyst_a_token(client: AsyncClient, seed_data) -> str:
    return await _get_token(client, "analyst@alpha.test", "AnalystAlpha123!")


@pytest_asyncio.fixture
async def viewer_a_token(client: AsyncClient, seed_data) -> str:
    return await _get_token(client, "viewer@alpha.test", "ViewerAlpha123!")


@pytest_asyncio.fixture
async def admin_b_token(client: AsyncClient, seed_data) -> str:
    return await _get_token(client, "admin@beta.test", "AdminBeta123!")


@pytest_asyncio.fixture
async def ingestor_a_token(client: AsyncClient, seed_data) -> str:
    # F1 canonical ``ingestor`` role — T11.2 RBAC matrix requires the
    # 403 denials on every Assets endpoint. The seed inserts this user
    # alongside the other roles.
    return await _get_token(client, "ingestor@soc360.test", "IngestorAlpha123!")


@pytest_asyncio.fixture
async def superadmin_headers(superadmin_token: str) -> dict:
    return {"Authorization": f"Bearer {superadmin_token}"}


@pytest_asyncio.fixture
async def admin_a_headers(admin_a_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_a_token}"}


@pytest_asyncio.fixture
async def analyst_a_headers(analyst_a_token: str) -> dict:
    return {"Authorization": f"Bearer {analyst_a_token}"}


@pytest_asyncio.fixture
async def viewer_a_headers(viewer_a_token: str) -> dict:
    return {"Authorization": f"Bearer {viewer_a_token}"}


@pytest_asyncio.fixture
async def admin_b_headers(admin_b_token: str) -> dict:
    return {"Authorization": f"Bearer {admin_b_token}"}


@pytest_asyncio.fixture
async def ingestor_a_headers(ingestor_a_token: str) -> dict:
    return {"Authorization": f"Bearer {ingestor_a_token}"}


# ---------------------------------------------------------------------------
# Singleton isolation — reset module-level singletons between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_event_bus_singleton():
    """Reset the _event_bus singleton before/after each test for isolation."""
    import app.dependencies.event_deps

    app.dependencies.event_deps._event_bus = None
    yield
    import app.dependencies.event_deps

    app.dependencies.event_deps._event_bus = None


# ---------------------------------------------------------------------------
# Concurrency test infrastructure — real pooled connections for parallel tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="function")
async def pooled_engine():
    """Engine with a real connection pool for concurrency tests.

    Unlike the default NullPool fixture, this allows multiple concurrent
    sessions to obtain separate DB connections, which is required to prove
    advisory-lock serialization under parallel load.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        pool_size=10,
        max_overflow=10,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def isolated_db_session(pooled_engine):
    """Factory that yields function-scoped AsyncSession instances from a pooled engine.

    Usage in concurrency tests:
        session1 = isolated_db_session()
        session2 = isolated_db_session()
    Each call returns a fresh AsyncSession with its own DB connection.
    Note: isolated_db_session is a sync factory (not async) — do NOT await it.
    """
    session_factory = async_sessionmaker(
        bind=pooled_engine, class_=AsyncSession, expire_on_commit=False
    )
    sessions: list[AsyncSession] = []

    def _make_session() -> AsyncSession:
        s = session_factory()
        sessions.append(s)
        return s

    yield _make_session

    for s in sessions:
        await s.close()


# ---------------------------------------------------------------------------
# Toxiproxy session fixture — PR1 #260 baseline fault-injection harness
# ---------------------------------------------------------------------------
# Serial-only: the proxy is ONE global endpoint for the whole test run
# (a single proxy named ``redis`` listening on 0.0.0.0:26379). Under
# pytest-xdist, workers sharing it would race on the same toxic set and
# reset each other's state, so these fixtures skip instead —
# fault-injection tests run exclusively in CI's dedicated serial
# Toxiproxy gate (the parallel selection already excludes them).

TOXIPROXY_CLEANUP_TIMEOUT_SECONDS = 5.0


def _assert_serial_toxiproxy() -> None:
    """Fail closed when Toxiproxy fixtures run under pytest-xdist.

    The fault-injection proxy is a single shared endpoint for the whole
    test run (one proxy named ``redis`` listening on 0.0.0.0:26379, plus
    the serial-only DB flush below): two xdist workers touching it would
    race on the same toxic set and reset each other's state. Toxiproxy
    tests must run exclusively in CI's dedicated serial Toxiproxy gate.
    """
    worker_id = _xdist_worker_id()
    if worker_id:
        raise RuntimeError(
            "Toxiproxy fixture requested under pytest-xdist worker "
            f"{worker_id!r}: the fault-injection proxy (0.0.0.0:26379) is a "
            "single shared endpoint, so these fixtures are serial-only. Run "
            "them in the dedicated serial Toxiproxy gate instead."
        )


def _skip_toxiproxy_under_xdist() -> None:
    """Skip the calling Toxiproxy fixture when running under pytest-xdist."""
    try:
        _assert_serial_toxiproxy()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def toxiproxy_session():
    """Set up the Toxiproxy Redis proxy for the test session.

    Creates the proxy if it does not exist, ensures it is enabled,
    and asserts clean Redis state through the proxy. Setup and teardown
    failures are propagated because this is a mandatory CI baseline.
    Serial-only: skips under pytest-xdist because the proxy is a single
    shared endpoint (see the section comment above).
    """
    _skip_toxiproxy_under_xdist()
    from tests.helpers.toxiproxy import ToxiproxyTransportController

    controller = ToxiproxyTransportController()
    await controller.ensure_proxy(
        name="redis",
        listen="0.0.0.0:26379",
        upstream="redis:6379",
    )

    yield controller

    # Teardown: ensure proxy is re-enabled for the next session
    await controller.enable_proxy("redis")


async def _flush_toxiproxy_database() -> None:
    """Flush the disposable Redis database (db 15) used by integration tests.

    Serial-only by design: db 15 is the reserved serial app/Toxiproxy
    target, while each xdist worker gets its own db 1..13 — flushing it
    from a worker would wipe the shared serial state while the proxy is
    still shared. Fails closed under xdist (before any connection opens)
    instead of flushing an arbitrary worker DB.
    """
    _assert_serial_toxiproxy()
    async with Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=_SERIAL_APP_REDIS_DB,
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
    ) as client:
        await client.flushdb()


@pytest_asyncio.fixture(scope="function")
async def toxiproxy_client(toxiproxy_session):
    """Yield a clean function-scoped controller for the Redis proxy.

    Serial-only: skips under pytest-xdist because the proxy is a single
    shared endpoint (see the section comment above).
    """
    _skip_toxiproxy_under_xdist()

    async def reset_state() -> None:
        results = await asyncio.gather(
            toxiproxy_session.reset_toxics(),
            close_pool(),
            _flush_toxiproxy_database(),
            return_exceptions=True,
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        if failures:
            raise RuntimeError("Toxiproxy fixture cleanup failed") from failures[0]

    await asyncio.wait_for(reset_state(), timeout=TOXIPROXY_CLEANUP_TIMEOUT_SECONDS)
    try:
        yield toxiproxy_session
    finally:
        await asyncio.wait_for(reset_state(), timeout=TOXIPROXY_CLEANUP_TIMEOUT_SECONDS)
