"""FastAPI dependency injection hub.

Re-exports all dependency functions and type aliases for the application.
"""
from __future__ import annotations

from typing import Annotated, TypeAlias

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db  # noqa: F401 — re-exported
from app.core.redis import get_redis  # noqa: F401 — re-exported
from app.dependencies.auth import (  # noqa: F401
    get_current_user,
    oauth2_scheme,
    require_role,
    require_superadmin,
)
from app.dependencies.cross_tenant import (  # noqa: F401
    _get_tenant_for_admin,
    _get_user_for_admin,
    _log_cross_tenant_attempt,
    _tenant_for_admin,
    _user_for_admin,
    get_tenant_for_admin_get,
    get_user_for_admin_delete,
    get_user_for_admin_get,
    get_user_for_admin_patch,
)
from app.dependencies.db_deps import get_db_with_tenant  # noqa: F401
from app.dependencies.event_deps import (  # noqa: F401
    _event_bus,
    get_event_bus,
)
from app.dependencies.llm_deps import get_llm  # noqa: F401
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

# ---------------------------------------------------------------------------
# FastAPI dependency type aliases — modern Annotated pattern
# ---------------------------------------------------------------------------
DBDep: TypeAlias = Annotated[AsyncSession, Depends(get_db)]
RedisDep: TypeAlias = Annotated[Redis, Depends(get_redis)]
CurrentUserDep: TypeAlias = Annotated[User, Depends(get_current_user)]
SuperadminDep: TypeAlias = Annotated[User, Depends(require_superadmin)]
AdminDep: TypeAlias = Annotated[User, Depends(require_role("admin"))]
DBWithTenantDep: TypeAlias = Annotated[AsyncSession, Depends(get_db_with_tenant)]
UserForAdminGetDep: TypeAlias = Annotated[User, Depends(get_user_for_admin_get)]
UserForAdminPatchDep: TypeAlias = Annotated[User, Depends(get_user_for_admin_patch)]
UserForAdminDeleteDep: TypeAlias = Annotated[User, Depends(get_user_for_admin_delete)]
TenantForAdminGetDep: TypeAlias = Annotated[Tenant, Depends(get_tenant_for_admin_get)]
