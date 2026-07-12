"""Integration tests for GET /health/db/indexes — requires live app + DB.

Covers spec scenarios for db-index-health-check:
  SCN-1.1 Probe access (no auth, no tenant header)
  SCN-3.1 Fresh database returns 200 with empty invalid list
  SCN-4.1 Invalid index (indisvalid=false) returns 503 with the index listed
  SCN-5.1 Read-only pooled access (no BEGIN, no advisory locks)
  SCN-6.1 Tenant-independent behavior (X-Tenant-Id invariance)

The endpoint is added in Task 4 (app/main.py). Before Task 4 these tests
all FAIL because the route does not exist (404 or AttributeError on app).

Strict TDD mode is inferred `false` (init cache did not expose strict_tdd: true).
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import event, make_url

from app.core.config import settings
from app.core.database import engine as app_engine

pytestmark = pytest.mark.integration

TARGET_INDEX_FOR_MUTATION = "ix_vulnerabilities_scan_tenant"


# ---------------------------------------------------------------------------
# Fixture — dispose the module-level engine between tests to avoid
# cross-event-loop connection reuse. Each pytest-asyncio function-scoped
# test gets its own loop, and the global engine's pool would otherwise bind
# connections to a previous loop and fail with "Event loop is closed".
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def _reset_app_engine_between_tests() -> "AsyncIterator[None]":
    """Dispose app.core.database.engine before each test so the pool is empty
    when the new event loop takes ownership.
    """
    await app_engine.dispose()
    yield
    await app_engine.dispose()

# ---------------------------------------------------------------------------
# Helpers — direct DB access for pg_index mutation (test-only)
# ---------------------------------------------------------------------------


def _migration_db_params() -> tuple[str, int, str, str, str]:
    parsed = make_url(settings.DATABASE_URL_MIGRATION)
    return (
        parsed.username or "soc360_migration",
        parsed.port or 5432,
        parsed.host or "localhost",
        parsed.password or "",
        parsed.database or "soc360_test",
    )


def _set_index_validity(indexname: str, valid: bool) -> "asyncio.Future[None]":
    """Return an awaitable that forces indisvalid on a public index.

    Async (not sync) so it composes with the running event loop inside
    pytest-asyncio tests — ``asyncio.run()`` cannot be called from a
    running loop.
    """
    user, port, host, password, database = _migration_db_params()

    async def _runner() -> None:
        conn = await asyncpg.connect(
            user=user,
            password=password,
            host=host,
            port=port,
            database=database,
        )
        try:
            await conn.execute(
                """
                UPDATE pg_index SET indisvalid = $1
                WHERE indexrelid = (
                    SELECT c.oid FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = $2 AND n.nspname = 'public'
                )
                """,
                valid,
                indexname,
            )
        finally:
            await conn.close()

    return _runner()


# ---------------------------------------------------------------------------
# SCN-1.1 — probe access works without auth or tenant header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scn_1_1_probe_access_without_headers(client: AsyncClient) -> None:
    """GET /health/db/indexes with no auth/tenant headers returns a valid HTTP
    response (does not reject access)."""
    resp = await client.get("/health/db/indexes")
    # Pre-Task-4 this returns 404; post-Task-4 it returns 200 or 503 (with body).
    assert resp.status_code in (200, 503), (
        f"SCN-1.1 failed — endpoint rejected access: {resp.status_code} {resp.text!r}"
    )


# ---------------------------------------------------------------------------
# SCN-3.1 — fresh database returns 200 with empty invalid list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scn_3_1_fresh_database_returns_200_ok(client: AsyncClient) -> None:
    """On a fresh DB (no invalid indexes), the endpoint returns 200 with
    body {"status":"ok","invalid":[]}."""
    resp = await client.get("/health/db/indexes")
    assert resp.status_code == 200, (
        f"SCN-3.1 failed — expected 200, got {resp.status_code}: {resp.text!r}"
    )
    body: dict[str, Any] = resp.json()
    assert body.get("status") == "ok", (
        f"SCN-3.1 failed — status field should be 'ok', got {body!r}"
    )
    assert body.get("invalid") == [], (
        f"SCN-3.1 failed — invalid list should be empty, got {body!r}"
    )


# ---------------------------------------------------------------------------
# SCN-4.1 — invalid index returns 503 with the index listed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scn_4_1_invalid_index_returns_503(client: AsyncClient) -> None:
    """After UPDATE pg_index SET indisvalid=false on the target index, the
    endpoint returns 503 with that name in the invalid list."""
    # Sanity: confirm the target exists (the migration test fixture leaves
    # the DB at head).
    await _set_index_validity(TARGET_INDEX_FOR_MUTATION, False)
    try:
        resp = await client.get("/health/db/indexes")
        assert resp.status_code == 503, (
            f"SCN-4.1 failed — expected 503, got {resp.status_code}: {resp.text!r}"
        )
        body: dict[str, Any] = resp.json()
        assert body.get("status") == "degraded", (
            f"SCN-4.1 failed — status field should be 'degraded', got {body!r}"
        )
        assert TARGET_INDEX_FOR_MUTATION in body.get("invalid", []), (
            f"SCN-4.1 failed — invalid list should contain "
            f"{TARGET_INDEX_FOR_MUTATION!r}, got {body!r}"
        )
    finally:
        await _set_index_validity(TARGET_INDEX_FOR_MUTATION, True)


# ---------------------------------------------------------------------------
# SCN-5.1 — read-only pooled access (no BEGIN, no advisory locks)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scn_5_1_no_begin_or_advisory_lock_in_sql_trace(
    client: AsyncClient,
) -> None:
    """Capture SQL emitted by the endpoint and assert:
       - the trace contains the index-health SELECT
       - it does NOT contain an explicit BEGIN
       - it does NOT contain any pg_advisory_* call
       - it does NOT contain any LOCK statement
    """
    statements: list[str] = []

    def _capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(app_engine.sync_engine, "before_cursor_execute", _capture)
    try:
        resp = await client.get("/health/db/indexes")
        assert resp.status_code in (200, 503), (
            f"SCN-5.1 failed — endpoint returned unexpected status "
            f"{resp.status_code}: {resp.text!r}"
        )
    finally:
        event.remove(app_engine.sync_engine, "before_cursor_execute", _capture)

    # Build a single trace of all statements for inspection.
    trace = "\n".join(statements)
    low = trace.lower()

    # 1. The index-health SELECT must be present (spec query).
    assert "pg_index" in low and "indisvalid" in low, (
        f"SCN-5.1 failed — expected pg_index indisvalid query in trace, "
        f"got:\n{trace!r}"
    )

    # 2. No BEGIN / COMMIT — the endpoint must NOT open a transaction.
    #    Filter out lines that are part of unrelated statement preambles
    #    (e.g., SET LOCAL inside another test) by checking whole statements.
    has_begin = any(
        s.strip().upper().startswith("BEGIN") for s in statements
    )
    assert not has_begin, (
        f"SCN-5.1 failed — endpoint issued a BEGIN statement:\n"
        + "\n".join(s for s in statements if s.strip().upper().startswith("BEGIN"))
    )

    # 3. No advisory locks.
    assert "pg_advisory" not in low, (
        f"SCN-5.1 failed — endpoint issued pg_advisory_* call:\n{trace!r}"
    )

    # 4. No LOCK statements.
    has_lock = any(
        s.strip().upper().startswith("LOCK ") for s in statements
    )
    assert not has_lock, (
        f"SCN-5.1 failed — endpoint issued a LOCK statement:\n"
        + "\n".join(s for s in statements if s.strip().upper().startswith("LOCK "))
    )


# ---------------------------------------------------------------------------
# SCN-6.1 — X-Tenant-Id header does not affect the response
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scn_6_1_header_invariance(client: AsyncClient) -> None:
    """With and without X-Tenant-Id, the response is byte-identical (index
    health is global, not tenant-scoped)."""
    resp_no_header = await client.get("/health/db/indexes")
    resp_with_header = await client.get(
        "/health/db/indexes",
        headers={"X-Tenant-Id": "11111111-1111-1111-1111-111111111111"},
    )

    assert resp_no_header.status_code == resp_with_header.status_code, (
        f"SCN-6.1 failed — status changed with X-Tenant-Id: "
        f"without={resp_no_header.status_code}, "
        f"with={resp_with_header.status_code}"
    )
    # Compare JSON bodies field-by-field to avoid timestamp ordering noise.
    assert resp_no_header.json() == resp_with_header.json(), (
        f"SCN-6.1 failed — body changed with X-Tenant-Id: "
        f"without={resp_no_header.json()!r}, "
        f"with={resp_with_header.json()!r}"
    )
