"""Integration concurrency test for tenant ``max_assets`` enforcement."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from sqlalchemy import delete, func, select

from app.core.database import get_session_with_tenant
from app.event_bus import EventBus
from app.modules.assets.models import Asset
from app.modules.assets.schemas import IpAssetCreate
from app.modules.assets.service import AssetLimitExceededError, create_asset
from app.modules.tenants.models import Tenant

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_concurrent_create_asset_respects_max_assets() -> None:
    """Two concurrent creates against ``max_assets=1`` yield 1 success and 1 limit error."""
    tenant_id = uuid4()
    async with get_session_with_tenant(None, is_superadmin=True) as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"Concurrency {tenant_id.hex[:8]}",
                slug=f"concurrency-{tenant_id.hex[:12]}",
                plan="free",
                is_active=True,
                max_assets=1,
            )
        )
        await session.commit()

    async def _attempt(ip_value: str) -> Asset:
        bus = EventBus(FakeRedis(decode_responses=True))
        async with get_session_with_tenant(tenant_id, is_superadmin=False) as session:
            return await create_asset(
                data=IpAssetCreate(
                    tenant_id=tenant_id,
                    type="ip",
                    value=ip_value,
                ),
                tenant_id=tenant_id,
                db=session,
                event_bus=bus,
            )

    try:
        results = await asyncio.gather(
            _attempt("203.0.113.10"),
            _attempt("203.0.113.11"),
            return_exceptions=True,
        )

        successes = [r for r in results if isinstance(r, Asset)]
        limit_errors = [r for r in results if isinstance(r, AssetLimitExceededError)]
        other_errors = [
            r
            for r in results
            if isinstance(r, BaseException)
            and not isinstance(r, AssetLimitExceededError)
        ]

        assert not other_errors, f"Unexpected errors: {other_errors!r}"
        assert len(successes) == 1, f"Expected 1 success, got {results!r}"
        assert len(limit_errors) == 1, f"Expected 1 limit error, got {results!r}"

        async with get_session_with_tenant(tenant_id, is_superadmin=False) as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(Asset)
                    .where(Asset.tenant_id == tenant_id)
                )
            ).scalar_one()
            assert count == 1
    finally:
        async with get_session_with_tenant(None, is_superadmin=True) as session:
            await session.execute(delete(Asset).where(Asset.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
