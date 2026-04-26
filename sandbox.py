from __future__ import annotations

import os
import sys

# Esto es para que se pueda importar los módulos del proyecto
sys.path.insert(0, os.path.dirname(__file__))

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.modules.tenants.models import Tenant
from app.modules.tenants.schemas import TenantCreate
from sqlalchemy import select, text, update, delete

async def main() -> None:
    """Probamos las conexiones y algunas queries"""
    print(f"Conectando a: {settings.DATABASE_URL!r}")

    async with AsyncSessionLocal() as db:
        # Configurar contexto como superadmin para bypassear RLS
        await db.execute(
            text("SELECT set_config('app.is_superadmin', 'true', true)")
        )
        # 1. Contar tenants
        result = await db.execute(select(Tenant))
        tenants = result.scalars().all()
        print(f"\nTotal tenants: {len(tenants)}")

        # 2. Mostrar cada tenant
        for t in tenants:
            print(f"  -{t.name} (slug={t.slug}, plan={t.plan})")

        # # 2. Crear un tenant
        # data = TenantCreate(name="Mi empresa")
        # tenant = Tenant(
        #     name=data.name.strip(),
        #     slug="mi-empresa-2",
        #     plan=data.plan,
        #     is_active=True,
        #     max_assets=10,
        #     settings={},
        # )
        # db.add(tenant)
        # await db.flush()
        # await db.refresh(tenant)
        # print(f"\nCreado: {tenant.name} (id={tenant.id})")

        # 3. Consultar al que creamos
        result = await db.execute(select(Tenant).where(Tenant.slug == "mi-empresa"))
        encontrado = result.scalar_one_or_none()
        print(f"Consultado: {encontrado}")
        print(f"Antes: plan={encontrado.plan}")
        await db.execute(update(Tenant).where(Tenant.slug == "mi-empresa").values(plan="starter"))
        await db.refresh(encontrado)
        print(f"Despues: plan={encontrado.plan}")
        # Delete
        print(f"Antes del borrado: {encontrado}")
        await db.execute(delete(Tenant).where(Tenant.slug == "mi-empresa-2"))
        await db.refresh(encontrado)
        print(f"Despues del borrado: {encontrado}")
        await db.commit()

if __name__=="__main__":
    import asyncio
    
    asyncio.run(main()) 
