"""Add approved_by_user_id to asset ownership declarations.

S1 (H1): a ``method="declaration"`` row is no longer verified when it is
recorded. A superadmin approves it, and the approval records who did it, so the
table needs that column, its index and its user foreign key.

Revision ID: c4d8e2b1a7f3
Revises: b3f1c7a9d4e2
Create Date: 2026-11-25 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d8e2b1a7f3"
down_revision: str | None = "b3f1c7a9d4e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "asset_ownership_declarations"


def upgrade() -> None:
    # Nullable on purpose: the challenge methods are verified by publishing the
    # token, not by a person, and a removed approver account must not erase the
    # declaration it approved.
    op.add_column(
        TABLE,
        sa.Column("approved_by_user_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        f"fk_{TABLE}_approved_by_user_id",
        TABLE,
        "users",
        ["approved_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        f"ix_{TABLE}_approved_by_user_id",
        TABLE,
        ["approved_by_user_id"],
    )
    # ADD COLUMN does not change the table's policy posture, but it is asserted
    # here so a future change to this table cannot quietly drop the tenant
    # isolation the declarations depend on (both statements are idempotent).
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index(f"ix_{TABLE}_approved_by_user_id", table_name=TABLE)
    op.drop_constraint(f"fk_{TABLE}_approved_by_user_id", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "approved_by_user_id")
