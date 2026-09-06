"""align assets model for slice 1

Revision ID: e0eafdf389fc
Revises: a1b2c3d4e5f6
Create Date: 2026-09-06 20:09:09.528975

Slice 1 of F2 Assets — aligns the existing `assets` table (created by
``20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py``) to the
slice-1 contract:

* Rename ``assets.name`` (NOT NULL varchar(255)) → ``assets.value``.
* Drop the ``assets.hostname`` column.
* Extend ``chk_assets_asset_type`` to the six-value allowlist
  ``('hostname','domain','ip','web_app','subnet','cloud_resource')``,
  remapping any existing ``'host'`` rows to ``'hostname'`` first.
* Add ``uq_assets_tenant_type_value`` UNIQUE
  (``tenant_id``, ``asset_type``, ``value``).

The pre-existing constraint ``chk_assets_status`` and the composite
identity ``uq_assets_id_tenant_id`` are left untouched, as are the
triggers, indexes, grants, and the ``rls_assets`` policy.

The ``upgrade()`` and ``downgrade()`` functions are all-or-nothing: any
pre-existing condition that would invalidate the new constraint raises
``RuntimeError(...)`` BEFORE the first DDL statement. The preconditions
run only in online mode (a real DB connection); the offline ``--sql``
render path skips them because ``op.get_bind()`` is not available.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import context, op

# revision identifiers, used by Alembic.
revision: str = 'e0eafdf389fc'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Six-value asset_type allowlist introduced by Slice 1.
NEW_ASSET_TYPES_SQL = (
    "asset_type IN ('hostname','domain','ip','web_app','subnet','cloud_resource')"
)

# Historical four-value allowlist restored by downgrade.
OLD_ASSET_TYPES_SQL = (
    "asset_type IN ('host','domain','ip','web_app')"
)


def _is_offline_mode() -> bool:
    """Return True when alembic is rendering SQL (``--sql``)."""
    return context.is_offline_mode()


def upgrade() -> None:
    """Align `assets` to six types + `value` + unique.

    Raises ``RuntimeError(...)`` BEFORE any DDL when the new
    ``uq_assets_tenant_type_value`` would conflict with pre-existing
    duplicate ``(tenant_id, asset_type, name)`` rows.
    """
    if not _is_offline_mode():
        conn = op.get_bind()
        dup_rows = conn.execute(
            sa.text(
                "SELECT tenant_id, asset_type, name, count(*) AS n "
                "FROM assets GROUP BY tenant_id, asset_type, name "
                "HAVING count(*) > 1"
            )
        ).fetchall()
        if dup_rows:
            raise RuntimeError(
                "Cannot add uq_assets_tenant_type_value: existing duplicates "
                f"({len(dup_rows)} groups). Resolve before running upgrade."
            )

    # Drop the four-value check before renaming/recreating so the
    # `UPDATE host → hostname` step is not rejected.
    op.drop_constraint("chk_assets_asset_type", "assets", type_="check")
    op.alter_column("assets", "name", new_column_name="value")
    op.drop_column("assets", "hostname")
    op.execute(
        "UPDATE assets SET asset_type='hostname' WHERE asset_type='host'"
    )
    op.create_check_constraint(
        "chk_assets_asset_type", "assets", NEW_ASSET_TYPES_SQL,
    )
    op.create_unique_constraint(
        "uq_assets_tenant_type_value", "assets",
        ["tenant_id", "asset_type", "value"],
    )


def downgrade() -> None:
    """Reverse Slice 1 alignment to the four-type pre-migration shape.

    Raises ``RuntimeError(...)`` BEFORE any DDL when the BD contains rows
    with ``asset_type IN ('subnet', 'cloud_resource')`` — those literals
    cannot survive the four-value check.
    """
    if not _is_offline_mode():
        conn = op.get_bind()
        new_types = conn.execute(
            sa.text(
                "SELECT count(*) FROM assets "
                "WHERE asset_type IN ('subnet', 'cloud_resource')"
            )
        ).scalar_one()
        if new_types:
            raise RuntimeError(
                "Cannot downgrade: rows with asset_type 'subnet' or "
                f"'cloud_resource' exist ({new_types}). Migrate or delete "
                "before downgrade."
            )

    op.drop_constraint(
        "uq_assets_tenant_type_value", "assets", type_="unique",
    )
    op.drop_constraint("chk_assets_asset_type", "assets", type_="check")
    op.execute(
        "UPDATE assets SET asset_type='host' WHERE asset_type='hostname'"
    )
    op.add_column(
        "assets",
        sa.Column("hostname", sa.String(length=255), nullable=True),
    )
    op.alter_column("assets", "value", new_column_name="name")
    op.create_check_constraint(
        "chk_assets_asset_type", "assets", OLD_ASSET_TYPES_SQL,
    )