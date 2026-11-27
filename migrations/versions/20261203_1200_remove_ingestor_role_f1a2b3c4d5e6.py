"""Remove unused ingestor role from chk_valid_role constraint.

S12 (L6): The ``ingestor`` role had no active endpoints or workflows and is
removed from the canonical RBAC roles (``viewer``, ``analyst``, ``admin``,
``superadmin``).

Revision ID: f1a2b3c4d5e6
Revises: e3a9c5b1f4d8
Create Date: 2026-12-03 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e3a9c5b1f4d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("chk_valid_role", "users", type_="check")
    op.create_check_constraint(
        "chk_valid_role",
        "users",
        "role IN ('viewer', 'analyst', 'admin', 'superadmin')",
    )


def downgrade() -> None:
    op.drop_constraint("chk_valid_role", "users", type_="check")
    op.create_check_constraint(
        "chk_valid_role",
        "users",
        "role IN ('viewer', 'analyst', 'ingestor', 'admin', 'superadmin')",
    )
