"""Integration test: statement_timeout kills long-running queries (issue #134).

Requires a real PostgreSQL instance. Skipped automatically when the DB is
unreachable.
"""
from __future__ import annotations

import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


def _pg_available() -> bool:
    """Return True if the test PostgreSQL is reachable."""
    import asyncio

    try:
        import asyncpg
    except ImportError:
        return False

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return False

    # Use SQLAlchemy's URL parser instead of a narrow regex — handles edge
    # cases like special characters in passwords, IPv6 hosts, etc.
    try:
        from sqlalchemy.engine.url import make_url
        parsed = make_url(db_url)
    except Exception:
        return False

    if parsed.drivername != "postgresql+asyncpg":
        return False

    async def _ping():
        conn = await asyncpg.connect(
            user=parsed.username or "",
            password=parsed.password or "",
            host=parsed.host or "localhost",
            port=parsed.port or 5432,
            database=parsed.database or "",
            timeout=3,
        )
        await conn.close()

    try:
        asyncio.run(_ping())
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not available",
)


@requires_pg
class TestStatementTimeoutIntegration:
    """Verify statement_timeout actually kills long-running queries."""

    @pytest.mark.asyncio
    async def test_pg_sleep_exceeds_statement_timeout(self):
        """A query exceeding statement_timeout MUST be cancelled by PostgreSQL.

        We create an engine with a very short statement_timeout (100ms) and
        run pg_sleep(5) which should be killed well before 5 seconds.
        """
        # Use a dedicated engine with a tight timeout for this test
        test_url = os.environ["DATABASE_URL"]
        engine = create_async_engine(
            test_url,
            connect_args={
                "server_settings": {
                    "statement_timeout": "100",   # 100ms
                    "lock_timeout": "5000",
                },
            },
        )
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False,
        )

        try:
            async with session_factory() as session:
                with pytest.raises(Exception) as exc_info:
                    await session.execute(text("SELECT pg_sleep(5)"))

                # asyncpg raises asyncpg.QueryCancelled or similar; the key
                # assertion is that it DID raise, not that it completed.
                error_msg = str(exc_info.value).lower()
                assert (
                    "cancel" in error_msg
                    or "timeout" in error_msg
                    or "statement" in error_msg
                ), f"Expected timeout/cancel error, got: {exc_info.value}"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fast_query_succeeds_with_timeout_set(self):
        """A fast query MUST succeed even when statement_timeout is configured."""
        test_url = os.environ["DATABASE_URL"]
        engine = create_async_engine(
            test_url,
            connect_args={
                "server_settings": {
                    "statement_timeout": str(settings.DB_STATEMENT_TIMEOUT_MS),
                    "lock_timeout": str(settings.DB_LOCK_TIMEOUT_MS),
                },
            },
        )
        session_factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False,
        )

        try:
            async with session_factory() as session:
                result = await session.execute(text("SELECT 1 AS ok"))
                row = result.scalar()
                assert row == 1
        finally:
            await engine.dispose()
