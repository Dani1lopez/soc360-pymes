"""Worker persistence and post-scan enrichment delivery with no LLM or broker."""
from importlib import import_module
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, update

from app.core.config import settings
from app.core.database import set_tenant_context
from app.modules.enrichment.prompts import functions_for_level
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment
from app.modules.vulnerabilities.models import Vulnerability
from app.worker import tasks
from tests.conftest import TENANT_A_ID
from tests.integration.test_scan_state_transitions import (
    _cleanup_committed_scan,
    _enable_superadmin,
    _seed_committed_scan,
)

pytestmark = pytest.mark.integration


class FakeProvider:
    async def complete(self, prompt, max_tokens, temperature, *, system_prompt=None):
        return "Review the observed service weakness."


@pytest.fixture
async def committed_findings(isolated_db_session):
    scan_id, asset_id = await _seed_committed_scan(isolated_db_session, status="pending")
    tenant_id = UUID(TENANT_A_ID)
    ids = [uuid4(), uuid4()]
    async with isolated_db_session() as session:
        await _enable_superadmin(session)
        previous = await session.scalar(select(Tenant.ai_enrichment_level).where(Tenant.id == tenant_id))
        await session.execute(update(Tenant).where(Tenant.id == tenant_id).values(ai_enrichment_level="basic"))
        session.add_all([
            Vulnerability(id=id_, tenant_id=tenant_id, scan_id=scan_id,
                          title="Service weakness", description="Observed weakness", severity="high")
            for id_ in ids
        ])
        await session.commit()
    try:
        yield scan_id, tenant_id, ids
    finally:
        async with isolated_db_session() as session:
            await _enable_superadmin(session)
            await session.execute(delete(Vulnerability).where(Vulnerability.scan_id == scan_id))
            await session.execute(update(Tenant).where(Tenant.id == tenant_id).values(ai_enrichment_level=previous))
            await session.commit()
        await _cleanup_committed_scan(isolated_db_session, scan_id, asset_id)


async def test_enrich_commits_visible_rows(isolated_db_session, committed_findings):
    worker = import_module("app.worker.enrichment_tasks")
    _, tenant_id, ids = committed_findings
    result = await worker._enrich(str(ids[0]), str(tenant_id), None,
                                 provider_factory=FakeProvider, model_name=lambda: "test-model")
    assert result.succeeded == functions_for_level("basic")
    assert not result.has_failures
    async with isolated_db_session() as session:
        await set_tenant_context(session, tenant_id, False)
        rows = (await session.scalars(select(VulnerabilityEnrichment).where(
            VulnerabilityEnrichment.vulnerability_id == ids[0]
        ))).all()
        assert {row.function for row in rows} == set(result.succeeded)
        assert all(row.status == "ok" and row.model == "test-model" for row in rows)


@pytest.mark.parametrize("outcome", ["completed", "failed"])
async def test_wake_enqueues_only_completed_scan(monkeypatch, committed_findings, outcome):
    scan_id, tenant_id, ids = committed_findings
    monkeypatch.setattr(settings, "SCAN_EXECUTION_ENABLED", True)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)
    enqueue = AsyncMock(return_value=True)
    assert await tasks._wake(claim=AsyncMock(return_value=(scan_id, tenant_id)),
                             execute=AsyncMock(return_value=outcome),
                             enqueue_enrichment=enqueue) == outcome
    if outcome == "completed":
        assert enqueue.await_count == len(ids)
        assert {call.args[:2] for call in enqueue.await_args_list} == {
            (str(id_), str(tenant_id)) for id_ in ids
        }
    else:
        enqueue.assert_not_awaited()
