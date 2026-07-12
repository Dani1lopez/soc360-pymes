"""restore fk-child composite indexes and dropped user indexes (concurrent rebuild)

Revision ID: a1b2c3d4e5f6
Revises: c1d2e3f4a5b6
Create Date: 2026-07-11 17:00:00.000000

Rebuilds the four indexes that the legacy version of this migration created
without ``CONCURRENTLY``. Concurrent rebuilds are required because each
indexed table (``vulnerabilities``, ``reports``, ``users``) is large and
actively written — a blocking ``CREATE INDEX`` against them would freeze
all INSERT/UPDATE/DELETE on the affected tables during the migration.

Indexes rebuilt:
  1. ix_vulnerabilities_scan_tenant  — composite FK child for vulnerabilities
  2. ix_reports_asset_tenant         — composite FK child for reports
  3. ix_users_email_lower            — case-insensitive email lookup (was dropped)
  4. ix_users_tenant_active          — tenant-scoped active user listing (was dropped)

Post-upgrade, each index's definition is re-read from ``pg_indexes`` and its
``pg_index`` flag triple (``indisvalid``, ``indisready``, ``indislive``) is
checked. A state mismatch raises ``RuntimeError`` so an unhealthy concurrent
build fails the migration instead of leaving a silently-broken index. To
prevent a permanent lockup when a previous concurrent attempt already left
the index name present-but-invalid, ``_concurrent_create`` drops and
rebuilds it concurrently so a migration retry self-heals. Both catalog
checks are skipped in offline ``--sql`` mode (which has no live
connection to read them back).

``ix_scans_asset_tenant`` already exists (created by ``c1d2e3f4a5b6``) and is
verified but not created here.

Expression index ``lower(email)`` requires raw ``op.execute()``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import context, op
from sqlalchemy import text

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Substrings expected in pg_indexes.indexdef for each target index after a
# successful build. PostgreSQL renders these identically regardless of whether
# the build was concurrent or not, so capturing them once from a fresh DB
# run gives us a stable contract for _assert_index_def().
#
# Captured against soc360_test on 2026-07-12. If the substrings ever drift
# (e.g., a future PostgreSQL minor version renders expressions differently),
# update this dict after re-running Task 0 capture.
_EXPECTED_INDEX_DEFS: dict[str, str] = {
    "ix_vulnerabilities_scan_tenant": (
        "ON public.vulnerabilities USING btree (scan_id, tenant_id)"
    ),
    "ix_reports_asset_tenant": ("ON public.reports USING btree (asset_id, tenant_id)"),
    "ix_users_email_lower": ("ON public.users USING btree (lower((email)::text))"),
    "ix_users_tenant_active": ("ON public.users USING btree (tenant_id, is_active)"),
}


def _concurrent_create(name: str, table: str, expr: str) -> None:
    """Create a btree index concurrently, outside Alembic's per-migration transaction.

    REQ-2: each CREATE INDEX CONCURRENTLY MUST execute inside its own
    ``op.get_context().autocommit_block()`` because PostgreSQL refuses to
    run concurrent DDL inside an explicit transaction.

    Auto-recovery: a previous concurrent build may have left the index row
    present-but-invalid (``indisvalid=false``). Against that, plain
    ``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` no-ops while the runtime
    check below would still raise. To prevent the schema from locking up
    behind the missing name, this helper probes ``pg_index`` via
    ``_index_exists_and_is_invalid`` and — when an invalid index is found
    — drops it concurrently inside its own ``autocommit_block()`` before
    the CREATE step. Both the probe and the recovery drop are skipped in
    offline ``--sql`` mode (no live catalog to inspect or mutate).
    """
    if not context.is_offline_mode() and _index_exists_and_is_invalid(name):
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    sql = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} " f"ON {table} {expr}"
    with op.get_context().autocommit_block():
        op.execute(sql)


def _concurrent_drop(name: str) -> None:
    """Drop an index concurrently, outside Alembic's per-migration transaction.

    Symmetric counterpart of ``_concurrent_create`` — concurrent drops
    cannot run inside an explicit transaction either.
    """
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def _index_exists_and_is_invalid(name: str) -> bool:
    """Return True if a public-schema index named ``name`` exists with ``indisvalid`` false.

    Probed by ``_concurrent_create`` before its CREATE step: a previously-
    failed concurrent build can leave the index row in the catalog while
    unfit for the planner. PostgreSQL refuses ``CREATE INDEX CONCURRENTLY``
    against an existing index, and the ``IF NOT EXISTS`` clause masks the
    rebuild — without this pre-check the only recovery path is a manual
    ``DROP INDEX CONCURRENTLY`` issued by a human operator.
    """
    sql = text(
        """
        SELECT i.indisvalid
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = :n AND n.nspname = 'public'
        """
    )
    rows = op.get_bind().execute(sql, {"n": name}).fetchall()
    if not rows:
        return False
    return not bool(rows[0][0])


def _assert_index_def(name: str, expected_substring: str) -> None:
    """Confirm ``pg_indexes.indexdef`` contains the expected expression.

    REQ-3 (definition half). ``CREATE INDEX IF NOT EXISTS`` only checks the
    name; a same-named index with the wrong columns or a wrong expression
    would be silently accepted. Re-reading ``pg_indexes.indexdef`` and
    substring-matching fails loudly on definition drift.
    """
    bind = op.get_bind()
    indexdef = bind.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname='public' AND indexname=:n"
        ),
        {"n": name},
    ).scalar()
    if indexdef is None:
        raise RuntimeError(f"index {name!r} missing from pg_indexes")
    if expected_substring not in indexdef:
        raise RuntimeError(
            f"index {name!r} has unexpected definition: {indexdef!r} "
            f"does not contain {expected_substring!r}"
        )


def _assert_index_health(name: str) -> None:
    """Confirm ``pg_index`` flag triple for a public schema index.

    REQ-3 (state half). A successful concurrent build leaves
    ``indisvalid = indisready = indislive = true``. A failure mid-build can
    leave one or more flags false — the index exists but is not used by the
    planner. Detecting that here prevents shipping a silently-broken
    migration.
    """
    sql = text(
        """
        SELECT i.indisvalid, i.indisready, i.indislive
        FROM pg_index i
        JOIN pg_class c ON c.oid = i.indexrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relname = :n AND n.nspname = 'public'
        """
    )
    rows = op.get_bind().execute(sql, {"n": name}).fetchall()
    if not rows:
        raise RuntimeError(f"index {name!r} missing from pg_index")
    valid, ready, live = rows[0]
    bad = [
        flag
        for flag, value in (
            ("indisvalid", valid),
            ("indisready", ready),
            ("indislive", live),
        )
        if not value
    ]
    if bad:
        raise RuntimeError(
            f"index {name!r} has unhealthy pg_index flags: {bad} — "
            "rebuild failed; inspect concurrent build logs and retry migration."
        )


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # SAFETY GUARANTEE (REQ-4) — required by every CREATE INDEX CONCURRENTLY
    # below.
    #
    # PostgreSQL refuses to run CREATE INDEX CONCURRENTLY inside an explicit
    # transaction. Alembic opens a per-migration transaction in
    # do_run_migrations() (see migrations/env.py) — each concurrent
    # statement MUST exit it by entering
    # ``op.get_context().autocommit_block()``. The same applies to every
    # DROP INDEX CONCURRENTLY in downgrade().
    #
    # We always use CONCURRENTLY, even on empty tables:
    #   • Consistency: same code path in test and prod; no "production
    #     had a populated table, tests did not" foot-gun.
    #   • CONCURRENTLY on an empty table is cheap (one scan, no waiting).
    #   • Lock pattern is independent of population, so the migration is
    #     robust if data is inserted between the empty check and the DDL.
    # ─────────────────────────────────────────────────────────────────────

    _concurrent_create(
        "ix_vulnerabilities_scan_tenant",
        "vulnerabilities",
        "(scan_id, tenant_id)",
    )
    _concurrent_create(
        "ix_reports_asset_tenant",
        "reports",
        "(asset_id, tenant_id)",
    )
    _concurrent_create(
        "ix_users_email_lower",
        "users",
        "(lower(email::text))",
    )
    _concurrent_create(
        "ix_users_tenant_active",
        "users",
        "(tenant_id, is_active)",
    )

    # Live catalog state check (REQ-3) — skipped in offline --sql mode, which
    # has no live connection to read pg_indexes / pg_index back from.
    if not context.is_offline_mode():
        for name, expected_substring in _EXPECTED_INDEX_DEFS.items():
            _assert_index_def(name, expected_substring)
            _assert_index_health(name)


def downgrade() -> None:
    # ── SAFETY GUARANTEE (DROP INDEX CONCURRENTLY) ────────────────────────
    # Same autocommit rationale as upgrade — see the comment block there.
    # Each DROP must run outside the per-migration transaction.
    # ─────────────────────────────────────────────────────────────────────
    for name in (
        "ix_users_tenant_active",
        "ix_users_email_lower",
        "ix_reports_asset_tenant",
        "ix_vulnerabilities_scan_tenant",
    ):
        _concurrent_drop(name)
