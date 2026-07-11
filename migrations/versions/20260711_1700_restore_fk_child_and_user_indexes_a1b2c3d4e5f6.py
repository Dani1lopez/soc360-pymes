"""restore fk-child composite indexes and dropped user indexes

Creates 4 indexes:
  1. ix_vulnerabilities_scan_tenant  — composite FK child for vulnerabilities
  2. ix_reports_asset_tenant         — composite FK child for reports
  3. ix_users_email_lower            — case-insensitive email lookup (was dropped)
  4. ix_users_tenant_active          — tenant-scoped active user listing (was dropped)

Indexes 3 and 4 were originally created by migration 70dc591dac68 but were
dropped by a subsequent migration and never recreated. The ORM models already
declare them in __table_args__; this migration brings the database into sync.

ix_scans_asset_tenant already exists (created by c1d2e3f4a5b6) and is
verified but not created here.

Expression index lower(email) requires raw op.execute().

Revision ID: a1b2c3d4e5f6
Revises: c1d2e3f4a5b6
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import context, op
from sqlalchemy import text

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_index_def(name: str, required: list) -> None:
    """Assert that the index in pg_indexes matches the expected tokens.

    `CREATE INDEX IF NOT EXISTS` only checks the NAME; a same-named index with
    wrong columns/expression would be silently accepted. We re-read
    ``pg_indexes.indexdef`` and confirm every required substring is present
    (matching is case-insensitive). On mismatch we raise to surface the drift
    instead of pretending the schema is correct.
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
        raise RuntimeError(f"index {name!r} missing after CREATE")
    low = indexdef.lower()
    for token in required:
        if token not in low:
            raise RuntimeError(
                f"index {name!r} has an incompatible definition "
                f"(missing {token!r}): {indexdef}"
            )


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_vulnerabilities_scan_tenant "
        "ON vulnerabilities (scan_id, tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_reports_asset_tenant "
        "ON reports (asset_id, tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_email_lower " "ON users (lower(email))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_tenant_active "
        "ON users (tenant_id, is_active)"
    )

    # Validate: same-named indexes with wrong columns/expression would be
    # silently kept by IF NOT EXISTS. Re-read pg_indexes.indexdef and fail
    # loudly if any of the 4 expected definitions differs. Postgres renders
    # the expression index as `lower((email)::text)` so the token must use
    # that exact rendering. Skipped in offline mode (--sql), which has no
    # live connection to read pg_indexes back from.
    if not context.is_offline_mode():
        _assert_index_def(
            "ix_vulnerabilities_scan_tenant",
            ["on public.vulnerabilities", "(scan_id, tenant_id)"],
        )
        _assert_index_def(
            "ix_reports_asset_tenant",
            ["on public.reports", "(asset_id, tenant_id)"],
        )
        _assert_index_def(
            "ix_users_email_lower",
            ["on public.users", "lower((email)"],
        )
        _assert_index_def(
            "ix_users_tenant_active",
            ["on public.users", "(tenant_id, is_active)"],
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_tenant_active")
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower")
    op.execute("DROP INDEX IF EXISTS ix_reports_asset_tenant")
    op.execute("DROP INDEX IF EXISTS ix_vulnerabilities_scan_tenant")
