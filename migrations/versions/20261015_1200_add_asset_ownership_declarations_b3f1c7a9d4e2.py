"""Add asset ownership declarations.

Revision ID: b3f1c7a9d4e2
Revises: af8b4c7d2e96
Create Date: 2026-10-15 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1c7a9d4e2"
down_revision: str | None = "af8b4c7d2e96"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_ownership_declarations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("asset_id", sa.UUID(), nullable=False),
        sa.Column("declared_by_user_id", sa.UUID(), nullable=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="pending"
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_fingerprint", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "method IN ('declaration', 'dns_txt', 'http_file')",
            name="chk_asset_ownership_declarations_method",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'revoked', 'failed')",
            name="chk_asset_ownership_declarations_status",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["declared_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "tenant_id"],
            ["assets.id", "assets.tenant_id"],
            ondelete="CASCADE",
            name="fk_asset_ownership_declarations_asset_tenant",
        ),
    )
    op.create_index(
        "ix_asset_ownership_declarations_tenant_id",
        "asset_ownership_declarations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_asset_ownership_declarations_asset_tenant",
        "asset_ownership_declarations",
        ["asset_id", "tenant_id"],
    )
    op.create_index(
        "ix_asset_ownership_declarations_declared_by_user_id",
        "asset_ownership_declarations",
        ["declared_by_user_id"],
    )
    op.execute("""
        CREATE TRIGGER trg_asset_ownership_declarations_updated_at
        BEFORE UPDATE ON asset_ownership_declarations
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("ALTER TABLE asset_ownership_declarations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE asset_ownership_declarations FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY rls_asset_ownership_declarations ON asset_ownership_declarations
        USING (
            current_setting('app.is_superadmin', TRUE) = 'true'
            OR tenant_id::text = current_setting('app.current_tenant', TRUE)
        )
    """)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON asset_ownership_declarations "
        "TO soc360_app"
    )


def downgrade() -> None:
    # Dropping the table also removes its policy, trigger, indexes, and grants.
    op.drop_table("asset_ownership_declarations")
