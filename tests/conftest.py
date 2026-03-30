from __future__ import annotations

import asyncio
import os
from click import echo
import pytest
import pytest_asyncio

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import(
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text


os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://soc360_app:soc360_dev_password@localhost:5433/soc360_test")
os.environ.setdefault("DATABASE_URL_MIGRATION", "postgresql+asyncpg://soc360_migration:soc360_migration_password@localhost:5433/soc360_test")
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_tests_only_32chars_min")
os.environ.setdefault("GROQ_API_KEY", "gsk_test_fake_key_for_tests_only")
os.environ.setdefault("POSTGRES_USER", "soc360_app")
os.environ.setdefault("POSTGRES_PASSWORD", "soc360_dev_password")
os.environ.setdefault("POSTGRES_DB", "soc360_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")


from app.main import create_app
from app.core.database import Base, set_tenant_context
from app.core.security import hash_password
from app.core.redis import get_redis
from app.dependencies import get_db, get_db_with_tenant
from app.modules.users.models import User
from app.modules.tenants.models import Tenant


TENANT_A_ID = "11111111-1111-1111-1111-111111111111"
TENANT_B_ID = "22222222-2222-2222-2222-222222222222"

SUPERADMIN_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ADMIN_A_ID    = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ANALYST_A_ID  = "cccccccc-cccc-cccc-cccc-cccccccccccc"
VIEWER_A_ID   = "dddddddd-dddd-dddd-dddd-dddddddddddd"
ADMIN_B_ID    = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


TEST_DATABASE_URL = os.environ["DATABASE_URL"]

test_engine: AsyncEngine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """
    Sobreescribe el event loop de pytest-asyncio para usar uno por sesión.
    Necesario para que fixtures de scope="session" funcionen con async.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def prepare_database():
    """
    Crea todas las tablas en soc360_test al inicio.
    Las elimina al terminar para dejar la BD limpia.
    """
    async with test_engine.begin() as conn:
        from app.modules.tenants.models import Tenant # noqa: F401
        from app.modules.users.models import User # noqa: F401
        from app.modules.auth.models import RefreshToken # noqa: F401
        
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    """
    Sesión de test con rollback automático al terminar.
    Cada test trabaja sobre datos frescos.
    """
    async with TestSessionLocal() as session:
        await session.begin()
        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture
async def seed_data(db_session: AsyncSession):
    """ Inserta los tenants y usuarios mínimos necesarios para los tests."""
    from uuid import UUID
    
    superadmin = User(
        id=UUID(SUPERADMIN_ID),
        tenant_id=None,
        email="superadmin@soc360.test",
        hashed_password=hash_password("SuperAdmin123!"),
        full_name="Super Admin",
        role="superadmin",
        is_active=True,
        is_superadmin=True,
    )
    
    tenant_a = Tenant(
        id=UUID(TENANT_A_ID),
        name="Empresa Alpha",
        slug="empresa-alpha",
        plan="starter",
        is_active=True,
        max_assets=50,
    )

    tenant_b = Tenant(
        id=UUID(TENANT_B_ID),
        name="Empresa Beta",
        slug="empresa-beta",
        plan="free",
        is_active=True,
        max_assets=10,
    )

    admin_a = User(
        id=UUID(ADMIN_A_ID),
        tenant_id=UUID(TENANT_A_ID),
        email="admin@alpha.test",
        hashed_password=hash_password("AdminAlpha123!"),
        full_name="Admin Alpha",
        role="admin",
        is_active=True,
        is_superadmin=False,
    )

    analyst_a = User(
        id=UUID(ANALYST_A_ID),
        tenant_id=UUID(TENANT_A_ID),
        email="analyst@alpha.test",
        hashed_password=hash_password("AnalystAlpha123!"),
        full_name="Analyst Alpha",
        role="analyst",
        is_active=True,
        is_superadmin=False,
    )

    viewer_a = User(
        id=UUID(VIEWER_A_ID),
        tenant_id=UUID(TENANT_A_ID),
        email="viewer@alpha.test",
        hashed_password=hash_password("ViewerAlpha123!"),
        full_name="Viewer Alpha",
        role="viewer",
        is_active=True,
        is_superadmin=False,
    )

    admin_b = User(
        id=UUID(ADMIN_B_ID),
        tenant_id=UUID(TENANT_B_ID),
        email="admin@beta.test",
        hashed_password=hash_password("AdminBeta123!"),
        full_name="Admin Beta",
        role="admin",
        is_active=True,
        is_superadmin=False,
    )
    
    await db_session.execute(text("SET LOCAL app.is_superadmin = 'true'"))
    db_session.add_all([tenant_a, tenant_b])
    await db_session.flush()
    db_session.add_all([superadmin, admin_a, analyst_a, viewer_a, admin_b])
    await db_session.flush()
    
    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "superadmin": superadmin,
        "admin_a": admin_a,
        "analyst_a": analyst_a,
        "viewer_a": viewer_a,
        "admin_b": admin_b,
    }

@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """Cliente HTTP que apunta a la app FastAPI con la BD de test inyectada."""
    app = create_app()
    
    async def override_get_db():
        yield db_session
    
    async def override_get_db_with_tenant():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_db_with_tenant] = override_get_db_with_tenant
    
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


async def _get_token(client: AsyncClient, email: str, password: str) -> str:
    """Hace login y devuelve solo el access_token."""
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