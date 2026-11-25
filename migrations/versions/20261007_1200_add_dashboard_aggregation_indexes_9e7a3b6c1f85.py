"""add dashboard aggregation indexes

Revision ID: 9e7a3b6c1f85
Revises: 8d6f2a5b0e74
Create Date: 2026-10-07 12:00:00.000000

F2 slice 7: tenant-first indexes support dashboard counts and time-window aggregations.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9e7a3b6c1f85"
down_revision: Union[str, None] = "8d6f2a5b0e74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_vulnerabilities_tenant_status_severity",
        "vulnerabilities",
        ["tenant_id", "status", "severity"],
    )
    op.create_index(
        "ix_vulnerabilities_tenant_created_at",
        "vulnerabilities",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_vulnerabilities_tenant_closed_at",
        "vulnerabilities",
        ["tenant_id", "closed_at"],
        postgresql_where=sa.text("closed_at IS NOT NULL"),
    )
    op.create_index(
        "ix_scans_tenant_completed_at",
        "scans",
        ["tenant_id", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scans_tenant_completed_at", table_name="scans")
    op.drop_index("ix_vulnerabilities_tenant_closed_at", table_name="vulnerabilities")
    op.drop_index("ix_vulnerabilities_tenant_created_at", table_name="vulnerabilities")
    op.drop_index(
        "ix_vulnerabilities_tenant_status_severity", table_name="vulnerabilities"
    )
