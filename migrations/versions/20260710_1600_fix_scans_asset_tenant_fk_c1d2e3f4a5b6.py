"""enforce tenant-scoped scan asset references

Revision ID: c1d2e3f4a5b6
Revises: bfca7016cbb7
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "bfca7016cbb7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DO $$
        DECLARE mismatch_count bigint;
        BEGIN
            SELECT COUNT(*) INTO mismatch_count
            FROM scans s JOIN assets a ON a.id = s.asset_id
            WHERE s.tenant_id <> a.tenant_id;
            IF mismatch_count > 0 THEN
                RAISE EXCEPTION 'cross-tenant scan/asset rows detected: %', mismatch_count;
            END IF;
        END $$;
    """)
    op.create_index("ix_scans_asset_tenant", "scans", ["asset_id", "tenant_id"])
    op.execute("""
        ALTER TABLE scans ADD CONSTRAINT fk_scans_asset_tenant
        FOREIGN KEY (asset_id, tenant_id) REFERENCES assets (id, tenant_id)
        ON DELETE CASCADE NOT VALID
    """)
    op.execute("ALTER TABLE scans VALIDATE CONSTRAINT fk_scans_asset_tenant")
    op.drop_constraint("scans_asset_id_fkey", "scans", type_="foreignkey")
    op.drop_index("ix_scans_asset_id", table_name="scans")


def downgrade() -> None:
    op.drop_constraint("fk_scans_asset_tenant", "scans", type_="foreignkey")
    op.drop_index("ix_scans_asset_tenant", table_name="scans")
    op.create_index("ix_scans_asset_id", "scans", ["asset_id"], unique=False)
    op.create_foreign_key(
        "scans_asset_id_fkey", "scans", "assets", ["asset_id"], ["id"], ondelete="CASCADE"
    )
