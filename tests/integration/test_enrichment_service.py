"""Real persistence with scripted, network-free provider calls."""
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.modules.enrichment.service import enrich_vulnerability
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import set_tenant_context
from app.core.exceptions import LLMError, VulnerabilityError
from app.modules.assets.models import Asset
from app.modules.enrichment.prompts import (
    PROMPT_VERSIONS,
    EnrichmentInput,
    build_prompt,
    functions_for_level,
    input_hash,
)
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment
from app.modules.vulnerabilities.models import Vulnerability
from tests.conftest import TENANT_A_ID

pytestmark = pytest.mark.integration
BASIC = functions_for_level("basic")
TEXT = "Address CVE-2024-1234 and CWE-79, not CVE-2099-9999 or CWE-999."


class FakeProvider:
    def __init__(self, finding: Vulnerability, outcomes=None, delays=None):
        snapshot = EnrichmentInput.from_vulnerability(finding)
        self.functions = {
            build_prompt(function, snapshot, "en").system: function
            for function in functions_for_level("full")
        }
        self.outcomes = outcomes or {}
        self.delays = delays or {}
        self.calls = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def complete(self, prompt, max_tokens, temperature, *, system_prompt=None):
        function = self.functions[system_prompt]
        self.calls.append((function, prompt, max_tokens, temperature, system_prompt))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delays.get(function, 0))
            outcome = self.outcomes.get(function, TEXT)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self.in_flight -= 1


@pytest_asyncio.fixture
async def finding(db_session: AsyncSession, seed_data):
    tenant_id = UUID(TENANT_A_ID)
    await set_tenant_context(db_session, None, is_superadmin=True)
    await db_session.execute(update(Tenant).where(Tenant.id == tenant_id).values(
        ai_enrichment_level="basic"
    ))
    asset = Asset(id=uuid4(), tenant_id=tenant_id, value="enrichment.test", asset_type="hostname")
    db_session.add(asset)
    await db_session.flush()
    scan = Scan(id=uuid4(), tenant_id=tenant_id, asset_id=asset.id,
                name="enrichment", scan_type="vulnerability")
    db_session.add(scan)
    await db_session.flush()
    vuln = Vulnerability(id=uuid4(), tenant_id=tenant_id, scan_id=scan.id,
                         title="Service weakness", description="Observed weakness",
                         severity="high", cve_id="CVE-2024-1234",
                         vulnerability_metadata={"cwe": ["CWE-79"]})
    db_session.add(vuln)
    await db_session.flush()
    await set_tenant_context(db_session, tenant_id, is_superadmin=False)
    return vuln


async def _run(db, finding, provider, **overrides):
    options = {"model": "test-model", "language": "en", "max_concurrency": 3, "budget_seconds": 5}
    options.update(overrides)
    return await enrich_vulnerability(db, finding.id, provider=provider, **options)


async def _rows(db, finding):
    rows = (await db.scalars(select(VulnerabilityEnrichment).where(
        VulnerabilityEnrichment.vulnerability_id == finding.id
    ).execution_options(populate_existing=True))).all()
    return {row.function: row for row in rows}


async def test_basic_success_filters_citations_and_preserves_transaction(db_session, finding):
    provider = FakeProvider(finding)
    # A service commit would close this caller-owned savepoint.
    savepoint = await db_session.begin_nested()
    result = await _run(db_session, finding, provider)
    assert savepoint.is_active
    assert result.succeeded == BASIC and result.failed == result.skipped == ()
    assert not result.has_failures
    rows = await _rows(db_session, finding)
    assert set(rows) == set(BASIC)
    for function, row in rows.items():
        assert row.status == "ok" and row.error is None and row.attempts == 1
        assert row.tenant_id == finding.tenant_id and row.model == "test-model"
        assert row.prompt_version == PROMPT_VERSIONS[function]
        assert row.input_hash == input_hash(EnrichmentInput.from_vulnerability(finding), "en")
        assert "CVE-2024-1234" in row.content and "CWE-79" in row.content
        assert "CVE-2099-9999" not in row.content and "CWE-999" not in row.content
    assert len(provider.calls) == 3
    for _, prompt, tokens, temperature, system in provider.calls:
        assert prompt.startswith("<finding>") and system
        assert tokens == settings.LLM_MAX_TOKENS and temperature == settings.LLM_TEMPERATURE
    await savepoint.rollback()
    assert await _rows(db_session, finding) == {}


async def test_second_run_skips_all_without_provider_calls(db_session, finding):
    await _run(db_session, finding, FakeProvider(finding))
    provider = FakeProvider(finding)
    result = await _run(db_session, finding, provider)
    assert result.skipped == BASIC and result.succeeded == result.failed == ()
    assert provider.calls == []
    assert all(row.attempts == 1 for row in (await _rows(db_session, finding)).values())


async def test_description_change_reruns_all(db_session, finding):
    await _run(db_session, finding, FakeProvider(finding))
    old_hash = (await _rows(db_session, finding))[BASIC[0]].input_hash
    finding.description = "New scan evidence"
    await db_session.flush()
    provider = FakeProvider(finding)
    result = await _run(db_session, finding, provider)
    assert result.succeeded == BASIC and result.skipped == ()
    assert len(provider.calls) == 3
    assert all(row.attempts == 2 and row.input_hash != old_hash
               for row in (await _rows(db_session, finding)).values())


async def test_provider_failure_preserves_content_and_retry_recovers(db_session, finding):
    function = BASIC[0]
    await _run(db_session, finding, FakeProvider(finding), only_functions=[function])
    original = (await _rows(db_session, finding))[function].content
    result = await _run(db_session, finding, FakeProvider(finding, {function: LLMError("scripted")}),
                        model="replacement-model", only_functions=[function])
    row = (await _rows(db_session, finding))[function]
    assert result.failed == (function,) and result.has_failures
    assert row.status == "failed" and row.error == "provider_error" and row.attempts == 2
    assert row.content == original and row.model == "replacement-model"
    result = await _run(db_session, finding, FakeProvider(finding, {function: "Recovered"}),
                        model="replacement-model", only_functions=[function])
    row = (await _rows(db_session, finding))[function]
    assert result.succeeded == (function,)
    assert row.status == "ok" and row.error is None and row.attempts == 3
    assert row.content == "Recovered"


async def test_blank_output_is_failed(db_session, finding):
    function = BASIC[0]
    result = await _run(db_session, finding, FakeProvider(finding, {function: " \n\t"}),
                        only_functions=[function])
    row = (await _rows(db_session, finding))[function]
    assert result.failed == (function,) and result.has_failures
    assert row.status == "failed" and row.error == "empty_output"
    assert row.content is None and row.attempts == 1


async def test_concurrency_is_bounded(db_session, finding):
    provider = FakeProvider(finding, delays=dict.fromkeys(BASIC, 0.03))
    result = await _run(db_session, finding, provider, max_concurrency=2)
    assert result.succeeded == BASIC
    assert provider.max_in_flight == 2 and provider.in_flight == 0


async def test_budget_keeps_completed_results_and_fails_slow_function(db_session, finding):
    slow = BASIC[-1]
    provider = FakeProvider(finding, delays={slow: 10})
    result = await _run(db_session, finding, provider, budget_seconds=0.2)
    rows = await _rows(db_session, finding)
    assert result.succeeded == BASIC[:-1] and result.failed == (slow,)
    assert result.has_failures and result.skipped == ()
    assert rows[slow].status == "failed" and rows[slow].error == "budget_exceeded"
    assert rows[slow].attempts == 1 and rows[slow].content is None
    assert all(rows[function].status == "ok" for function in BASIC[:-1])
    assert provider.in_flight == 0


async def test_missing_vulnerability_raises_domain_not_found(db_session, finding):
    provider = FakeProvider(finding)
    with pytest.raises(VulnerabilityError) as exc:
        await enrich_vulnerability(db_session, uuid4(), provider=provider, model="test-model",
                                   language="en", max_concurrency=2, budget_seconds=5)
    assert exc.value.status_code == 404
    assert provider.calls == []
