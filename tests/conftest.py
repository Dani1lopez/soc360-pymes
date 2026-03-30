from __future__ import annotations

import asyncio
import os
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


os.environ.setdefault("ENVIRONMENT", "testing")
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