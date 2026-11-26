"""Add refresh token family and explicit rotation state.

S4 (user decision L4): reuse detection needs two persisted data points on
``refresh_tokens`` — the family a token belongs to and the rotation state that
proves a token was already exchanged.

* ``family_id`` starts at login and is inherited by every rotation. It is the
  scope the defensive revocation targets when an already-rotated token is
  presented again.
* ``rotated_to_id`` points at the successor created by the rotation. It is the
  explicit rotation marker, so the defensive branch never has to infer *why* a
  row was revoked (logout, session-cap eviction and password change also set
  ``revoked_at``).

``family_id`` carries a volatile ``gen_random_uuid()`` server default: PostgreSQL
evaluates it per row, so existing tokens each become their own family root
(no invented history) and any insert that has no rotation context — scripts,
fixtures, direct SQL — keeps working.

Revision ID: d7e1a4c9b2f6
Revises: c4d8e2b1a7f3
Create Date: 2026-12-01 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e1a4c9b2f6"
down_revision: str | None = "c4d8e2b1a7f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "refresh_tokens"


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "credential_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "family_id",
            sa.UUID(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("rotated_to_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        f"fk_{TABLE}_rotated_to_id",
        TABLE,
        TABLE,
        ["rotated_to_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # The defensive revocation filters by family, not by token hash.
    op.create_index(
        f"ix_{TABLE}_family_id",
        TABLE,
        ["family_id"],
    )
    # ADD COLUMN does not change the table's policy posture, but it is asserted
    # here so a future change to this table cannot quietly drop the tenant
    # isolation refresh tokens depend on (idempotent).
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("users", "credential_version")
    op.drop_index(f"ix_{TABLE}_family_id", table_name=TABLE)
    op.drop_constraint(f"fk_{TABLE}_rotated_to_id", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "rotated_to_id")
    op.drop_column(TABLE, "family_id")
