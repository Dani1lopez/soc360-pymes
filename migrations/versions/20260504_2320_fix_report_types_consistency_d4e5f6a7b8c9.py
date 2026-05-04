"""fix report types consistency

Revision ID: d4e5f6a7b8c9
Revises: 8f2c1a4b9d7e
Create Date: 2026-05-04 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "8f2c1a4b9d7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill legacy NULL values
    op.execute("""
        UPDATE tenants
        SET report_types = '["vulnerability"]'::jsonb
        WHERE report_types is NULL
    """)
    
    # Set server default for future inserts
    op.alter_column(
        "tenants",
        "report_types",
        server_default=sa.text("'[\"vulnerability\"]'::jsonb"),
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
    )
def downgrade() -> None:
    # Remove server default
    op.alter_column(
        "tenants",
        "report_types",
        server_default=None,
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
    )
