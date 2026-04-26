from __future__ import annotations
import asyncio, os, sys

sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantResponse
from sqlalchemy import select, text
from uuid import UUID

async def main():
    tenant_id = input("Ingrese el UUID del tenant: ").strip()
    uuid_id = UUID(tenant_id)
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
        
        result = await db.execute(select(Tenant).where(Tenant.id == uuid_id))
        tenant = result.scalar_one_or_none()
        
        if tenant is None:
            print("Tenant no encontrado")
            return
        
        print(TenantResponse.model_validate(tenant))

if __name__=="__main__":
    asyncio.run(main())
