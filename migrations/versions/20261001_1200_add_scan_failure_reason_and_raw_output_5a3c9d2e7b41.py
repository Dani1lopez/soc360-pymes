"""add scan failure reason and raw output

Revision ID: 5a3c9d2e7b41
Revises: f92b1c0fa120
Create Date: 2026-10-01 12:00:00.000000

F2 slice 5 (PR 5a): every non-silent scan outcome must be explainable and
auditable.

- ``failure_reason`` — short, bounded machine-readable reason (e.g.
  ``timeout``, ``connect_fallback``, ``oversize_output``) set only when the
  scan ends ``failed``. Bounded ``VARCHAR(64)`` so a buggy or runaway reason
  can never bloat the row; the executor owns the vocabulary.
- ``raw_output`` — the full raw nmap XML stdout, stored as ``TEXT`` for
  parsing and audit.

Both are nullable: every row that predates the executor predates both
columns, and a scan may legitimately end ``completed`` without a reason.
Forward-only revision on the single head chain.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "5a3c9d2e7b41"
down_revision: Union[str, None] = "f92b1c0fa120"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "scans",
        sa.Column("raw_output", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scans", "raw_output")
    op.drop_column("scans", "failure_reason")
