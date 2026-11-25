"""add scan ready index

Revision ID: 7c5e1f4a9d63
Revises: 6b4d0e3f8c52
Create Date: 2026-10-04 12:00:00.000000

F2 slice 6: index the Postgres queue in global FIFO order.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7c5e1f4a9d63"
down_revision: Union[str, None] = "6b4d0e3f8c52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_scans_ready",
        "scans",
        ["dispatched_at", "id"],
        postgresql_where=sa.text("status = 'pending' AND dispatched_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_scans_ready", table_name="scans")
