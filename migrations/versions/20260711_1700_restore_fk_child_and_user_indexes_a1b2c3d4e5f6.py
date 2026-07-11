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

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_tenant_active")
    op.execute("DROP INDEX IF EXISTS ix_users_email_lower")
    op.execute("DROP INDEX IF EXISTS ix_reports_asset_tenant")
    op.execute("DROP INDEX IF EXISTS ix_vulnerabilities_scan_tenant")
