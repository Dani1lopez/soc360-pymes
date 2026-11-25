"""enforce one open scan name per asset

Revision ID: f92b1c0fa120
Revises: e0eafdf389fc
Create Date: 2026-09-19 23:12:35.057786

Adds the Slice 2 business rule: at most one OPEN (``pending``) scan per
``(tenant_id, asset_id, name)``. It is a partial unique index so the name is
released once the scan leaves ``pending``, which lets an asset be re-scanned
under the same name after a run finishes.

If pre-existing rows already violate the rule, ``upgrade()`` aborts with an
actionable error BEFORE executing any DDL. It never deletes or renames rows:
resolving the duplicates is an operator decision. Without this check the
CREATE UNIQUE INDEX would surface as a raw PostgreSQL error mid-migration.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import context, op
from sqlalchemy import text

revision: str = "f92b1c0fa120"
down_revision: Union[str, None] = "e0eafdf389fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "uq_scans_tenant_asset_name_pending"
PENDING_PREDICATE = "status = 'pending'"

_DUPLICATE_QUERY = text(
    "SELECT tenant_id, asset_id, name, count(*) AS occurrences "
    "FROM scans WHERE status = 'pending' "
    "GROUP BY tenant_id, asset_id, name HAVING count(*) > 1"
)


def duplicate_open_name_message(duplicates: Sequence[tuple]) -> str | None:
    """Return the abort message for the offending rows, or None when there are none.

    Kept free of any database access so the decision can be tested directly.
    """
    if not duplicates:
        return None

    shown = "; ".join(
        f"tenant={row[0]} asset={row[1]} name={row[2]!r} x{row[3]}"
        for row in duplicates[:10]
    )
    remainder = len(duplicates) - 10
    suffix = f" (+{remainder} more)" if remainder > 0 else ""
    return (
        f"Cannot create {INDEX_NAME}: {len(duplicates)} open name group(s) already "
        f"violate the rule that only one pending scan may share a name per asset. "
        f"Cancel, complete or rename them and retry. Offending groups: {shown}{suffix}"
    )


def upgrade() -> None:
    if not context.is_offline_mode():
        duplicates = op.get_bind().execute(_DUPLICATE_QUERY).fetchall()
        message = duplicate_open_name_message(duplicates)
        if message is not None:
            raise RuntimeError(message)

    op.create_index(
        INDEX_NAME,
        "scans",
        ["tenant_id", "asset_id", "name"],
        unique=True,
        postgresql_where=text(PENDING_PREDICATE),
    )


def downgrade() -> None:
    op.drop_index(
        INDEX_NAME,
        table_name="scans",
        postgresql_where=text(PENDING_PREDICATE),
    )
