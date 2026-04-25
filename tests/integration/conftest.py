"""Integration test configuration using real PostgreSQL + Alembic migrations.

This conftest is loaded ONLY for tests under tests/integration/.
It overrides the session-scoped prepare_database fixture to use real
Alembic migrations instead of the Base.metadata.create_all() approach.

Gate 0: tests must run against real schema (not no-op) so that functional
failures are real bugs, not missing schema.
"""
from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys

import pytest

# Global marker for all tests in this directory
pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(items):
    """Forcefully mark all tests in tests/integration/ with the integration marker.

    This ensures `pytest -m integration` works even when pytestmark in conftest
    alone doesn't reliably propagate to the test collection.
    """
    integration_path = "tests/integration"
    for item in items:
        if integration_path in str(item.fspath):
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------
# Helpers — safe logging (never print credentials)
# ---------------------------------------------------------------------------

def _db_url_for_log(url: str) -> str:
    """Mask password in DATABASE_URL for error messages."""
    if not url:
        return "<not set>"
    parts = url.split("@")
    if len(parts) == 2:
        creds = parts[0].replace("postgresql+asyncpg://", "")
        return f"postgresql+asyncpg://{creds.split(':')[0]}:***@{parts[1]}"
    return url


def _sanitize_output(text: str, db_url: str = "") -> str:
    """Remove database URLs and credentials from Alembic output.

    Prevents accidental credential leakage via stderr/stdout in error messages
    or logs. Strips the full postgresql+asyncpg://user:pass@host:port/db format.
    """
    if not text:
        return text
    # Remove DATABASE_URL in all its forms (postgresql+asyncpg, postgresql, etc.)
    text = re.sub(
        r"postgresql(?:\+asyncpg)?://[^@]+@[^/\s]+/[^\s]*",
        "[DB_URL_REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    # Fallback: if db_url was provided, mask it explicitly
    if db_url:
        text = text.replace(db_url, "[DB_URL_REDACTED]")
    return text


def _run_alembic_upgrade(dry_run: bool = False, db_url: str = "") -> None:
    """Apply Alembic migrations via subprocess (avoids import-time side-effects).

    Raises RuntimeError if alembic fails or DB is unreachable.
    """
    # project_root is the repo root where alembic.ini lives
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cmd = [
        sys.executable, "-m", "alembic", "upgrade", "head",
    ]
    env = {**os.environ, "PYTHONPATH": project_root}

    try:
        result = subprocess.run(
            cmd,
            cwd=project_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "Alembic upgrade timed out after 60s. "
            "Check if PostgreSQL is reachable."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to run alembic: {e}")

    if result.returncode != 0:
        stderr = _sanitize_output(result.stderr.strip(), db_url)
        safe_db_url = _db_url_for_log(db_url)
        raise RuntimeError(
            f"Alembic upgrade failed (exit {result.returncode}).\n"
            f"DB URL (safe): {safe_db_url}\n"
            f"stderr: {stderr}"
        )

    if dry_run:
        stdout = _sanitize_output(result.stdout.strip(), db_url)
        safe_db_url = _db_url_for_log(db_url)
        print(f"[prepare_database] Alembic dry-run OK for {safe_db_url}")
        if stdout:
            print(f"[prepare_database] stdout: {stdout}")


# ---------------------------------------------------------------------------
# Session-scoped fixture — runs ONCE per test session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def prepare_database():
    """Apply Alembic migrations to the test database.

    Fails fast with a clear message if:
    - DATABASE_URL is not set
    - PostgreSQL is unreachable
    - Alembic upgrade fails
    """
    db_url = os.environ.get("DATABASE_URL", "")

    if not db_url:
        raise RuntimeError(
            "DATABASE_URL not set. Cannot run integration tests. "
            "Set it to a test PostgreSQL instance."
        )

    # Quick connectivity check before trying migrations
    try:
        import asyncpg
        import re
        # Extract connection params from DATABASE_URL
        # Format: postgresql+asyncpg://user:pass@host:port/dbname
        match = re.match(
            r"postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)",
            db_url,
        )
        if match:
            user, password, host, port, dbname = match.groups()
            async def _ping():
                conn = await asyncpg.connect(
                    user=user, password=password,
                    host=host, port=int(port), database=dbname,
                    timeout=5,
                )
                await conn.close()
            asyncio.run(_ping())
        else:
            # Fallback: try via SQLAlchemy
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text
            engine = create_async_engine(db_url, echo=False)
            async def _ping():
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
            asyncio.run(_ping())
            asyncio.run(engine.dispose())
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to test database. "
            f"DB URL (safe): {_db_url_for_log(db_url)}. "
            f"Error: {e}"
        )

    _run_alembic_upgrade(db_url=db_url)

    yield

    # Teardown: run alembic downgrade to base (optional, CI may handle this)
    # Skipped by default to preserve DB state for post-mortem inspection.
