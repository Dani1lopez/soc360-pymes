import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.database import Base 

# IMPORTANTE: estos imports parecen no usarse pero son obligatorios.
# Al importar cada modelo, se registra en Base.metadata y Alembic
# puede detectarlo en el autogenerate. Nunca eliminar sin verificar.
from app.modules.tenants.models import Tenant  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from app.modules.auth.models import RefreshToken  # noqa: F401
from app.modules.assets.models import Asset  # noqa: F401
from app.modules.scans.models import Scan  # noqa: F401
from app.modules.vulnerabilities.models import Vulnerability  # noqa: F401
from app.modules.reports.models import Report  # noqa: F401



#Objeto configuracion de Alembic
config = context.config

# Configurar el logging desde alembic.ini 
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", settings.DATABASE_URL_MIGRATION)


def run_migrations_offline() -> None:
    """Modo offline: genera SQL sin conectarse a la BD"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    "Logica sincrona de migracion"
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Modo online: conecta async y ejecuta migraciones"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


# Punto de entreda
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
