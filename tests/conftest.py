from __future__ import annotations

import asyncio
import os
import subprocess
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
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://soc360_app:***REMOVED***@localhost:5434/soc360_test",
)
os.environ.setdefault(
    "DATABASE_URL_MIGRATION",
    "postgresql+asyncpg://soc360_migration:***REMOVED***@localhost:5434/soc360_test",
)
os.environ.setdefault(
    "SECRET_KEY",
    "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
    "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz"
    "abcdefghijklmnopqrstuvwx",
)
os.environ.setdefault("GROQ_API_KEY", "***REMOVED***")
os.environ.setdefault("POSTGRES_USER", "soc360_app")
os.environ.setdefault("POSTGRES_PASSWORD", "***REMOVED***")
os.environ.setdefault("POSTGRES_DB", "soc360_test")
# Structured Redis settings (PR1 #260 — REDIS_URL is rejected)
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_DB", "15")
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

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
MIGRATION_DATABASE_URL = os.environ["DATABASE_URL_MIGRATION"]


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
        app_password = app_parsed.password or "***REMOVED***"
        try:
            role_exists = await conn.fetchval(
                "SELECT 1 FROM pg_roles WHERE rolname = 'soc360_app'"
            )
            action = "ALTER" if role_exists else "CREATE"
            await conn.execute(
                f"{action} ROLE soc360_app WITH LOGIN PASSWORD '{app_password}' "
                "NOSUPERUSER NOBYPASSRLS"
            )
        finally:
            await conn.close()

    async def _setup() -> None:
        _assert_safe_test_database()
        await _ensure_app_role()
        # Drop everything and re-run the full Alembic chain so RLS policies,
        # GRANTs, triggers, and indexes are created exactly as in production.
        _run_alembic("downgrade", "base")
        _run_alembic("upgrade", "head")

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
    from app.dependencies import event_deps
    from app.event_bus import EventBus as _FakeEventBus

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

    async def _auth_get_event_bus() -> "EventBus":  # type: ignore[name-defined]
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
    test_redis = _RealAsyncRedis(
        host=_settings.REDIS_HOST,
        port=_settings.REDIS_PORT,
        db=14,
        # Local test Redis on :6379 runs without AUTH (the daemonized
        # redis-server in this dev env didn't accept --requirepass because
        # the port was already bound). Production-like settings still carry
        # REDIS_PASSWORD; the test client intentionally drops it to match.
        password=None,
        decode_responses=True,
    )
    try:
        await test_redis.ping()
    except Exception as exc:  # pragma: no cover - env guard
        await test_redis.aclose()
        raise RuntimeError(
"tenant_client fixture requires a reachable Redis on "
f"{_settings.REDIS_HOST}:{_settings.REDIS_PORT} db=14. "
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

        # Reuse the existing singleton if one is already cached; only
        # build a fresh bus when nothing has been resolved yet. The
        # spy in TestEventsSpy calls ``event_deps.get_event_bus()``
        # which materialises the singleton, then monkeypatches
        # ``bus.publish``. Subsequent invocations from the request
        # handler must hit the SAME instance so the spy observes the
        # publish. Constructing a new bus here would silently bypass
        # the patch (the test sees ``Expected 1 publish; got []``).
        if event_deps._event_bus is None:
            event_deps._event_bus = _TestEventBus(test_redis)
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

TOXIPROXY_CLEANUP_TIMEOUT_SECONDS = 5.0


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def toxiproxy_session():
    """Set up the Toxiproxy Redis proxy for the test session.

    Creates the proxy if it does not exist, ensures it is enabled,
    and asserts clean Redis state through the proxy. Setup and teardown
    failures are propagated because this is a mandatory CI baseline.
    """
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
    """Flush only the disposable Redis database used by integration tests."""
    async with Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        db=15,
        password=os.environ.get("REDIS_PASSWORD") or None,
        decode_responses=True,
    ) as client:
        await client.flushdb()


@pytest_asyncio.fixture(scope="function")
async def toxiproxy_client(toxiproxy_session):
    """Yield a clean function-scoped controller for the Redis proxy."""

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
