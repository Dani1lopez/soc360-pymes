"""App-role privilege validation tests.

Covers spec requirements #11–#15:
  #11 App role NOT superuser
  #12 App role NOT BYPASSRLS
  #13 App role does not own application tables
  #14 App role DDL rejection (destructive and constructive)
  #15 CI role separation (dual-role architecture)

RED phase: expected to fail when soc360_app runs as SUPERUSER.
GREEN phase: after CI hardening (WU-6), all MUST pass.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_app_role_not_superuser(
    db_session: AsyncSession,
):
    """Spec #11: soc360_app must NOT be a superuser."""
    result = await db_session.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = 'soc360_app'")
    )
    row = result.fetchone()
    assert row is not None, "soc360_app role not found in pg_roles"
    assert row[0] is False, "soc360_app has rolsuper=true — RLS is completely bypassed"


@pytest.mark.asyncio
async def test_app_role_not_bypassrls(
    db_session: AsyncSession,
):
    """Spec #12: soc360_app must NOT have BYPASSRLS."""
    result = await db_session.execute(
        text("SELECT rolbypassrls FROM pg_roles WHERE rolname = 'soc360_app'")
    )
    row = result.fetchone()
    assert row is not None, "soc360_app role not found in pg_roles"
    assert (
        row[0] is False
    ), "soc360_app has rolbypassrls=true — RLS policies are circumvented"


@pytest.mark.asyncio
async def test_app_role_owns_no_tables(
    db_session: AsyncSession,
):
    """Spec #13: No application table is owned by soc360_app."""
    result = await db_session.execute(
        text(
            "SELECT c.relname, c.relowner::regrole::text AS owner "
            "FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' "
            "AND c.relkind IN ('r', 'p') "
            "AND c.relowner = ("
            "  SELECT oid FROM pg_roles WHERE rolname = 'soc360_app'"
            ")"
        )
    )
    owned = result.fetchall()
    assert len(owned) == 0, (
        f"soc360_app owns {len(owned)} table(s): {[r[0] for r in owned]} — "
        "application role must not own tables"
    )


@pytest.mark.asyncio
async def test_destructive_ddl_drop_table_fails(
    db_session: AsyncSession,
):
    """Spec #14: DROP TABLE on application tables must raise permission denied."""
    with pytest.raises(ProgrammingError):
        await db_session.execute(text("DROP TABLE IF EXISTS assets CASCADE"))
    await db_session.rollback()


@pytest.mark.asyncio
async def test_destructive_ddl_alter_table_fails(
    db_session: AsyncSession,
):
    """Spec #14: ALTER TABLE on application tables must raise permission denied."""
    with pytest.raises(ProgrammingError):
        await db_session.execute(text("ALTER TABLE assets RENAME TO assets_renamed"))
    await db_session.rollback()


@pytest.mark.asyncio
async def test_constructive_ddl_fails(
    db_session: AsyncSession,
):
    """Spec #14: CREATE TABLE must raise permission denied."""
    with pytest.raises(ProgrammingError):
        await db_session.execute(text("CREATE TABLE hacker_table (id int)"))
