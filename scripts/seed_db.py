from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from argparse import ArgumentParser
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# setup_logging ANTES de cualquier get_logger — redacción de datos sensibles
# activa desde el primer momento, nunca después
from app.core.logging import setup_logging
setup_logging()

from app.core.logging import get_logger                          # noqa: E402
from sqlalchemy import text                                      # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.exc import OperationalError                      # noqa: E402
from app.core.config import settings                             # noqa: E402
from app.core.database import AsyncSessionLocal, get_session_with_tenant  # noqa: E402
from app.core.security import hash_password                      # noqa: E402
from app.modules.tenants.models import Tenant                    # noqa: E402
from app.modules.users.models import User                        # noqa: E402

logger = get_logger(__name__)

# ── Guard de entorno ─────────────────────────────────────────────────────────
# Bloquea ejecución fuera de desarrollo.


_ALLOWED_SEED_ENVIRONMENTS = {"development"}

if settings.ENVIRONMENT not in _ALLOWED_SEED_ENVIRONMENTS:
    print(f"❌  Seed bloqueado en entorno '{settings.ENVIRONMENT}'.")
    print(f"    Solo permitido en: {_ALLOWED_SEED_ENVIRONMENTS}")
    sys.exit(1)

# ── UUIDs fijos y deterministas ──────────────────────────────────────────────
# Fijos para que los tests de integración puedan hacer asserts con IDs concretos
# sin depender de la generación aleatoria de uuid4().

SEED_TENANT_ID     = uuid.UUID("00000000-0000-0000-0000-000000000001")
SEED_SUPERADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
SEED_ADMIN_ID      = uuid.UUID("00000000-0000-0000-0000-000000000011")
SEED_ANALYST_ID    = uuid.UUID("00000000-0000-0000-0000-000000000012")
SEED_VIEWER_ID     = uuid.UUID("00000000-0000-0000-0000-000000000013")

# ── Contraseñas desde entorno con fallback explícito ─────────────────────────
# Débiles por diseño (solo dev). Para cambiarlas sin tocar código:
#   SEED_SUPERADMIN_PASSWORD=xxx python scripts/seed_db.py

_SUPERADMIN_PASS = os.getenv("SEED_SUPERADMIN_PASSWORD", "Superadmin1234!")
_ADMIN_PASS      = os.getenv("SEED_ADMIN_PASSWORD",      "Admin1234!")
_ANALYST_PASS    = os.getenv("SEED_ANALYST_PASSWORD",    "Analyst1234!")
_VIEWER_PASS     = os.getenv("SEED_VIEWER_PASSWORD",     "Viewer1234!")

# ── Datos de seed ────────────────────────────────────────────────────────────
# Los hashes bcrypt se calculan aquí UNA SOLA VEZ al arrancar el script.
# Si estuvieran dentro de las funciones seed o en constantes de módulo
# evaluadas en import time, pytest los recalcularía en cada test file
# que importe este módulo (~100ms × 4 hashes × N test files = segundos perdidos).

def _build_seed_data() -> tuple[dict, dict, list[dict]]:
    """Construye los datos de seed calculando los hashes una sola vez."""

    tenant = {
        "id": SEED_TENANT_ID,
        "name": "Acme Corp",
        "slug": "acme-corp",
        "plan": "starter",
        "max_assets": 20,
        "is_active": True,
        "settings": {
            "notification_email": "admin@acme.com",
            "scan_schedule": "0 2 * * *",
            "severity_threshold": "medium",
            "timezone": "Europe/Madrid",
            "scan_limits": {"daily_max": 10, "concurrent_max": 2},
            "log_buffer_max": 500,
            "baseline_reset_requested": False,
        },
    }

    superadmin = {
        "id": SEED_SUPERADMIN_ID,
        "email": "superadmin@soc360.local",
        "full_name": "Super Admin",
        "role": "superadmin",
        "is_superadmin": True,
        "is_active": True,
        "tenant_id": None,
        "hashed_password": hash_password(_SUPERADMIN_PASS),
    }

    tenant_users = [
        {
            "id": SEED_ADMIN_ID,
            "email": "admin@acme.com",
            "full_name": "Admin Acme",
            "role": "admin",
            "is_superadmin": False,
            "is_active": True,
            "tenant_id": SEED_TENANT_ID,
            "hashed_password": hash_password(_ADMIN_PASS),
        },
        {
            "id": SEED_ANALYST_ID,
            "email": "analyst@acme.com",
            "full_name": "Analyst Acme",
            "role": "analyst",
            "is_superadmin": False,
            "is_active": True,
            "tenant_id": SEED_TENANT_ID,
            "hashed_password": hash_password(_ANALYST_PASS),
        },
        {
            "id": SEED_VIEWER_ID,
            "email": "viewer@acme.com",
            "full_name": "Viewer Acme",
            "role": "viewer",
            "is_superadmin": False,
            "is_active": True,
            "tenant_id": SEED_TENANT_ID,
            "hashed_password": hash_password(_VIEWER_PASS),
        },
    ]

    return tenant, superadmin, tenant_users


# ── Métricas de ejecución ────────────────────────────────────────────────────

@dataclass
class SeedStats:
    created: int = 0
    skipped: int = 0
    errors:  int = 0
    details: list[str] = field(default_factory=list)

    def record_created(self, label: str) -> None:
        self.created += 1
        self.details.append(f"  ✅ creado:  {label}")

    def record_skipped(self, label: str) -> None:
        self.skipped += 1
        self.details.append(f"  ⏭️  existía: {label}")

    def record_error(self, label: str, reason: str) -> None:
        self.errors += 1
        self.details.append(f"  ❌ error:   {label} — {reason}")


# ── Comprobación de conexión ─────────────────────────────────────────────────

async def check_db_connection() -> None:
    """Falla rápido con mensaje accionable si PostgreSQL no está disponible."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except OperationalError as exc:
        print("\n❌  No se puede conectar a PostgreSQL.")
        print("    ¿Está Docker corriendo?  →  docker compose up -d")
        print("    ¿Se aplicó la migración? →  alembic upgrade head")
        print(f"    Detalle: {exc.orig}\n")
        sys.exit(1)


# ── Funciones de seed ────────────────────────────────────────────────────────

async def seed_tenant(
    tenant_data: dict,
    stats: SeedStats,
    dry_run: bool,
) -> None:
    t0 = time.monotonic()
    label = f"Tenant '{tenant_data['slug']}'"

    if dry_run:
        logger.info("seed.dry_run", entity=label)
        stats.record_created(f"{label} (dry-run)")
        return

    async with get_session_with_tenant(None, is_superadmin=True) as db:
        # RETURNING id: única forma fiable de saber si asyncpg insertó o no.
        # rowcount con asyncpg en INSERT...ON CONFLICT puede devolver -1
        # tanto si inserta como si no — no es fiable para esta distinción.
        stmt = (
            pg_insert(Tenant)
            .values(**tenant_data)
            .on_conflict_do_nothing(index_elements=["slug"])
            .returning(Tenant.id)
        )
        result = await db.execute(stmt)
        was_inserted = result.scalar_one_or_none() is not None

    elapsed = round((time.monotonic() - t0) * 1000)

    if was_inserted:
        logger.info("seed.tenant_created", slug=tenant_data["slug"],
                    id=str(tenant_data["id"]), elapsed_ms=elapsed)
        stats.record_created(label)
    else:
        logger.info("seed.tenant_skip", slug=tenant_data["slug"], elapsed_ms=elapsed)
        stats.record_skipped(label)


async def seed_user(
    user_data: dict,
    is_superadmin_context: bool,
    stats: SeedStats,
    dry_run: bool,
) -> None:
    """Inserta un único usuario. Sesión propia — un fallo no afecta a los demás."""
    t0 = time.monotonic()
    label = f"User '{user_data['email']}' ({user_data['role']})"

    if dry_run:
        logger.info("seed.dry_run", entity=label)
        stats.record_created(f"{label} (dry-run)")
        return

    tenant_ctx = None if is_superadmin_context else user_data.get("tenant_id")

    try:
        async with get_session_with_tenant(tenant_ctx, is_superadmin=is_superadmin_context) as db:
            stmt = (
                pg_insert(User)
                .values(**user_data)
                .on_conflict_do_nothing(index_elements=["email"])
                .returning(User.id)
            )
            result = await db.execute(stmt)
            was_inserted = result.scalar_one_or_none() is not None

        elapsed = round((time.monotonic() - t0) * 1000)

        if was_inserted:
            logger.info("seed.user_created", email=user_data["email"],
                        role=user_data["role"], elapsed_ms=elapsed)
            stats.record_created(label)
        else:
            logger.info("seed.user_skip", email=user_data["email"], elapsed_ms=elapsed)
            stats.record_skipped(label)

    except Exception as exc:
        logger.error("seed.user_error", email=user_data["email"], error=str(exc))
        stats.record_error(label, str(exc))


# ── Entry point ──────────────────────────────────────────────────────────────

async def main(dry_run: bool = False) -> None:
    t_start = time.monotonic()
    stats = SeedStats()

    logger.info("seed.start", environment=settings.ENVIRONMENT, dry_run=dry_run)

    if not dry_run:
        await check_db_connection()

    # Hashes calculados una sola vez aquí, no en import time ni en cada llamada
    tenant_data, superadmin_data, tenant_users = _build_seed_data()

    try:
        await seed_tenant(tenant_data, stats, dry_run)
        await seed_user(superadmin_data, is_superadmin_context=True,  stats=stats, dry_run=dry_run)
        for user_data in tenant_users:
            await seed_user(user_data, is_superadmin_context=False, stats=stats, dry_run=dry_run)

    except Exception as exc:
        logger.error("seed.failed", error=str(exc))
        print(f"\n❌  Seed fallido inesperado: {exc}\n")
        sys.exit(1)

    elapsed = round((time.monotonic() - t_start) * 1000)
    logger.info(
        "seed.done",
        created=stats.created,
        skipped=stats.skipped,
        errors=stats.errors,
        elapsed_ms=elapsed,
    )

    # ── Resumen en consola ───────────────────────────────────────────────────
    prefix = "🔍 DRY-RUN — " if dry_run else ""
    print(f"\n{prefix}✅  Seed completado en {elapsed}ms")
    print(f"   Creados: {stats.created}  |  Ya existían: {stats.skipped}  |  Errores: {stats.errors}")

    if stats.details:
        print("\n   Detalle:")
        for line in stats.details:
            print(f"   {line}")

    if not dry_run:
        print("\n   ✅ Development users seeded (credentials configured)")

        if _SUPERADMIN_PASS == "superadmin1234":
            print(
                "\n   ⚠️   Usando contraseñas por defecto. "
                "Define SEED_*_PASSWORD en .env para cambiarlas."
            )

    if stats.errors:
        print(f"\n   ⚠️   {stats.errors} error(s) durante el seed. Revisa los logs.\n")
        sys.exit(1)

    print()


if __name__ == "__main__":
    parser = ArgumentParser(description="SOC360 — Seed de base de datos de desarrollo")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula el seed sin escribir nada en la BD",
    )
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))