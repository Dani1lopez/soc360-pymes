from __future__ import annotations

import asyncio
import os

import bcrypt
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from fakeredis.aioredis import FakeRedis

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://soc360_app:AppSoc360Pass2000futureDev@localhost:5433/soc360_test")
os.environ.setdefault("DATABASE_URL_MIGRATION", "postgresql+asyncpg://soc360_migration:MigSoc360Pass2005futureDev@localhost:5433/soc360_test")
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_tests_only_32chars_min")
os.environ.setdefault("GROQ_API_KEY", "gsk_test_fake_key_for_tests_only")
os.environ.setdefault("POSTGRES_USER", "soc360_app")
os.environ.setdefault("POSTGRES_PASSWORD", "soc360_dev_password")
os.environ.setdefault("POSTGRES_DB", "soc360_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app.main import create_app
from app.core.database import Base, set_tenant_context
from app.core.redis import get_redis
from app.dependencies import get_db, get_db_with_tenant
from app.modules.users.models import User
from app.modules.tenants.models import Tenant

TENANT_A_ID  = "11111111-1111-1111-1111-111111111111"
TENANT_B_ID  = "22222222-2222-2222-2222-222222222222"
SUPERADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ADMIN_A_ID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ANALYST_A_ID  = "cccccccc-cccc-cccc-cccc-cccccccccccc"
VIEWER_A_ID   = "dddddddd-dddd-dddd-dddd-dddddddddddd"
ADMIN_B_ID    = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"

TEST_DATABASE_URL = os.environ["DATABASE_URL"]


def _seed_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ✅ SYNC fixture — usa asyncio.run() para no contaminar ningún loop de test
@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    from app.modules.tenants.models import Tenant  # noqa: F401
    from app.modules.users.models import User       # noqa: F401
    from app.modules.auth.models import RefreshToken  # noqa: F401

    async def _setup() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    async def _teardown() -> None:
        engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_setup())
    yield
    asyncio.run(_teardown())


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    from uuid import UUID
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Idempotent tenant inserts — concurrency tests may have already committed these
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    await db_session.execute(
        pg_insert(Tenant).values(
            id=UUID(TENANT_A_ID), name="Empresa Alpha", slug="empresa-alpha",
            plan="starter", is_active=True, max_assets=50,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(Tenant).values(
            id=UUID(TENANT_B_ID), name="Empresa Beta", slug="empresa-beta",
            plan="free", is_active=True, max_assets=10,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.flush()

    # Idempotent user inserts
    await db_session.execute(
        pg_insert(User).values(
            id=UUID(SUPERADMIN_ID), tenant_id=None,
            email="superadmin@soc360.test", hashed_password=_seed_password_hash("SuperAdmin123!"),
            full_name="Super Admin", role="superadmin", is_active=True, is_superadmin=True,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User).values(
            id=UUID(ADMIN_A_ID), tenant_id=UUID(TENANT_A_ID),
            email="admin@alpha.test", hashed_password=_seed_password_hash("AdminAlpha123!"),
            full_name="Admin Alpha", role="admin", is_active=True, is_superadmin=False,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User).values(
            id=UUID(ANALYST_A_ID), tenant_id=UUID(TENANT_A_ID),
            email="analyst@alpha.test", hashed_password=_seed_password_hash("AnalystAlpha123!"),
            full_name="Analyst Alpha", role="analyst", is_active=True, is_superadmin=False,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User).values(
            id=UUID(VIEWER_A_ID), tenant_id=UUID(TENANT_A_ID),
            email="viewer@alpha.test", hashed_password=_seed_password_hash("ViewerAlpha123!"),
            full_name="Viewer Alpha", role="viewer", is_active=True, is_superadmin=False,
        ).on_conflict_do_nothing(index_elements=["id"])
    )
    await db_session.execute(
        pg_insert(User).values(
            id=UUID(ADMIN_B_ID), tenant_id=UUID(TENANT_B_ID),
            email="admin@beta.test", hashed_password=_seed_password_hash("AdminBeta123!"),
            full_name="Admin Beta", role="admin", is_active=True, is_superadmin=False,
        ).on_conflict_do_nothing(index_elements=["id"])
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

    return {
        "tenant_a": tenant_a, "tenant_b": tenant_b,
        "superadmin": superadmin, "admin_a": admin_a,
        "analyst_a": analyst_a, "viewer_a": viewer_a, "admin_b": admin_b,
    }


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    app = create_app()
    fake_redis = FakeRedis()  # ✅ mismo loop que el test (function scope)

    async def override_get_db():
        yield db_session

    async def override_get_db_with_tenant():
        yield db_session

    async def override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_with_tenant] = override_get_db_with_tenant
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


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
        session1 = await isolated_db_session()
        session2 = await isolated_db_session()
    Each call returns a fresh session with its own DB connection.
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
