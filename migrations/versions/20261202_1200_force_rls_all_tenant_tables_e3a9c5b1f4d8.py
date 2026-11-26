"""Force Row Level Security on all remaining tenant tables.

S10 (M1): ``vulnerability_enrichments`` and ``asset_ownership_declarations``
already enforce ``FORCE ROW LEVEL SECURITY``. The seven earlier tables only
had ``ENABLE ROW LEVEL SECURITY``, which allows a table owner to bypass RLS.
Applying ``FORCE ROW LEVEL SECURITY`` closes that gap fail-closed.

Revision ID: e3a9c5b1f4d8
Revises: d7e1a4c9b2f6
Create Date: 2026-12-02 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "e3a9c5b1f4d8"
down_revision: str | Sequence[str] | None = "d7e1a4c9b2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "tenants",
    "users",
    "refresh_tokens",
    "assets",
    "scans",
    "vulnerabilities",
    "reports",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
