"""add scan dispatched at

Revision ID: 6b4d0e3f8c52
Revises: 5a3c9d2e7b41
Create Date: 2026-10-02 12:00:00.000000

F2 slice 6: track enqueue time for the daily quota and the dispatch reaper.
Existing rows remain NULL, meaning never dispatched; no backfill is needed.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "6b4d0e3f8c52"
down_revision: Union[str, None] = "5a3c9d2e7b41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_scans_tenant_dispatched_at", "scans", ["tenant_id", "dispatched_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_scans_tenant_dispatched_at", table_name="scans")
    op.drop_column("scans", "dispatched_at")
