"""HTTP enrichment contracts; publishing is replaced by an in-process fake."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import update

from app.core.config import settings
from app.core.database import set_tenant_context
from app.modules.assets.models import Asset
from app.modules.enrichment.prompts import functions_for_level
from app.modules.scans.models import Scan
from app.modules.tenants.models import Tenant
from app.modules.vulnerabilities.enrichment_models import VulnerabilityEnrichment
from app.modules.vulnerabilities.models import Vulnerability
from tests.conftest import TENANT_A_ID, TENANT_B_ID

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def enrichment_enabled(monkeypatch):
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", True)


@pytest.fixture
async def enqueuer(tenant_client):
    # Deferred import keeps collection available before the router is implemented.
    from app.modules.enrichment.router import get_enrichment_enqueuer

    class Fake:
        def __init__(self):
            self.calls = []
            self.result = True

        async def __call__(self, vulnerability_id, tenant_id, only_functions=None):
            self.calls.append((vulnerability_id, tenant_id, only_functions))
            return self.result

    fake = Fake()
    tenant_client.app.dependency_overrides[get_enrichment_enqueuer] = lambda: fake
    try:
        yield fake
    finally:
        tenant_client.app.dependency_overrides.pop(get_enrichment_enqueuer, None)


async def _seed(db, tenant_id=TENANT_A_ID, count=1):
    await set_tenant_context(db, None, is_superadmin=True)
    await db.execute(
        update(Tenant).where(Tenant.id == UUID(tenant_id)).values(ai_enrichment_level="basic")
    )
    asset = Asset(id=uuid4(), tenant_id=UUID(tenant_id), asset_type="hostname", value=f"{uuid4()}.test")
    db.add(asset)
    await db.flush()
    scan = Scan(id=uuid4(), tenant_id=asset.tenant_id, asset_id=asset.id, name="enrichment", scan_type="vulnerability")
    db.add(scan)
    await db.flush()
    vulnerabilities = [
        Vulnerability(id=uuid4(), tenant_id=asset.tenant_id, scan_id=scan.id, title=f"Finding {i}", severity="high")
        for i in range(count)
    ]
    db.add_all(vulnerabilities)
    await db.flush()
    await db.commit()
    return scan, vulnerabilities


async def _rows(db, vulnerability, entries):
    await set_tenant_context(db, None, is_superadmin=True)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    for function, status in entries:
        db.add(VulnerabilityEnrichment(
            vulnerability_id=vulnerability.id, tenant_id=vulnerability.tenant_id,
            function=function, status=status, content=f"Saved {function}",
            error="provider_unavailable" if status == "failed" else None,
            model="test-model", prompt_version="1", attempts=2,
            input_hash="private-cache-identity", updated_at=timestamp,
        ))
    await db.flush()
    await db.commit()


def _url(vulnerability):
    return f"/api/v1/vulnerabilities/{vulnerability.id}/enrichment"


async def test_get_shape_level_scope_and_private_hash(tenant_client, admin_a_headers, db_session):
    _, (vulnerability,) = await _seed(db_session)
    await _rows(db_session, vulnerability, [("executive_summary", "ok"), ("contextual_severity", "failed"), ("hardening", "ok")])
    response = await tenant_client.get(_url(vulnerability), headers=admin_a_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"vulnerability_id", "level", "items"}
    assert body["vulnerability_id"] == str(vulnerability.id)
    assert body["level"] == "basic"
    items = body["items"]
    assert [item["function"] for item in items] == list(functions_for_level("basic"))
    assert [item["status"] for item in items] == ["ok", "failed", "missing"]
    for item in items:
        assert set(item) == {"function", "status", "content", "error", "model", "prompt_version", "attempts", "updated_at"}
    assert items[1]["content"] == "Saved contextual_severity"
    assert items[1]["error"] == "provider_unavailable"
    assert items[0]["model"] == "test-model"
    assert items[0]["prompt_version"] == "1"
    assert items[0]["attempts"] == 2
    assert datetime.fromisoformat(items[0]["updated_at"]) == datetime(2026, 1, 1, tzinfo=UTC)
    assert items[2]["updated_at"] is None
    assert items[2]["content"] is None
    assert "input_hash" not in response.text
    assert "private-cache-identity" not in response.text


@pytest.mark.parametrize("role,method,expected", [("viewer", "get", 200), ("viewer", "post", 403), ("ingestor", "get", 403), ("analyst", "post", 202)])
async def test_rbac(tenant_client, db_session, enqueuer, viewer_a_headers, ingestor_a_headers, analyst_a_headers, role, method, expected):
    headers = {"viewer": viewer_a_headers, "ingestor": ingestor_a_headers, "analyst": analyst_a_headers}[role]
    _, (vulnerability,) = await _seed(db_session)
    response = await getattr(tenant_client, method)(_url(vulnerability), headers=headers)
    assert response.status_code == expected, response.text
    assert len(enqueuer.calls) == (1 if expected == 202 else 0)


@pytest.mark.parametrize("method", ["get", "post"])
async def test_unauthenticated(tenant_client, method):
    response = await getattr(tenant_client, method)(f"/api/v1/vulnerabilities/{uuid4()}/enrichment")
    assert response.status_code == 401


@pytest.mark.parametrize("method", ["get", "post"])
async def test_other_tenant_vulnerability_is_404(tenant_client, admin_a_headers, db_session, enqueuer, method):
    _, (vulnerability,) = await _seed(db_session, TENANT_B_ID)
    response = await getattr(tenant_client, method)(_url(vulnerability), headers=admin_a_headers)
    assert response.status_code == 404, response.text
    assert enqueuer.calls == []


@pytest.mark.parametrize("resource", ["vulnerability", "scan"])
async def test_disabled(tenant_client, admin_a_headers, db_session, enqueuer, monkeypatch, resource):
    scan, (vulnerability,) = await _seed(db_session)
    monkeypatch.setattr(settings, "ENRICHMENT_ENABLED", False)
    url = _url(vulnerability) if resource == "vulnerability" else f"/api/v1/scans/{scan.id}/enrichment"
    response = await tenant_client.post(url, headers=admin_a_headers)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Enrichment is disabled"
    assert enqueuer.calls == []


@pytest.mark.parametrize("resource", ["vulnerability", "scan"])
async def test_publish_failure(tenant_client, admin_a_headers, db_session, enqueuer, resource):
    scan, (vulnerability,) = await _seed(db_session)
    enqueuer.result = False
    url = _url(vulnerability) if resource == "vulnerability" else f"/api/v1/scans/{scan.id}/enrichment"
    response = await tenant_client.post(url, headers=admin_a_headers)
    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Enrichment queue unavailable"
    assert enqueuer.calls == [(str(vulnerability.id), TENANT_A_ID, None)]


async def test_post_success(tenant_client, admin_a_headers, db_session, enqueuer):
    _, (vulnerability,) = await _seed(db_session)
    response = await tenant_client.post(_url(vulnerability), headers=admin_a_headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"queued": 1}
    assert enqueuer.calls == [(str(vulnerability.id), TENANT_A_ID, None)]


async def test_scan_queues_only_incomplete(tenant_client, admin_a_headers, db_session, enqueuer):
    scan, vulnerabilities = await _seed(db_session, count=4)
    complete, partial, failed, missing = vulnerabilities
    await _rows(db_session, complete, [(f, "ok") for f in functions_for_level("basic")])
    await _rows(db_session, partial, [("executive_summary", "ok"), ("hardening", "ok"), ("references", "ok")])
    await _rows(db_session, failed, [("executive_summary", "ok"), ("contextual_severity", "failed"), ("remediation", "pending")])
    response = await tenant_client.post(f"/api/v1/scans/{scan.id}/enrichment", headers=admin_a_headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"queued": 3, "total": 4}
    assert len(enqueuer.calls) == 3
    assert {call[0] for call in enqueuer.calls} == {str(v.id) for v in (partial, failed, missing)}
    assert all(call[1:] == (TENANT_A_ID, None) for call in enqueuer.calls)


@pytest.mark.parametrize("count", [0, 1])
async def test_scan_without_pending(tenant_client, admin_a_headers, db_session, enqueuer, count):
    scan, vulnerabilities = await _seed(db_session, count=count)
    for vulnerability in vulnerabilities:
        await _rows(db_session, vulnerability, [(f, "ok") for f in functions_for_level("basic")])
    response = await tenant_client.post(f"/api/v1/scans/{scan.id}/enrichment", headers=admin_a_headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"queued": 0, "total": count}
    assert enqueuer.calls == []


async def test_other_tenant_scan_is_404(tenant_client, admin_a_headers, db_session, enqueuer):
    scan, _ = await _seed(db_session, TENANT_B_ID)
    response = await tenant_client.post(f"/api/v1/scans/{scan.id}/enrichment", headers=admin_a_headers)
    assert response.status_code == 404, response.text
    assert enqueuer.calls == []


async def test_superadmin_uses_target_tenant(tenant_client, superadmin_headers, db_session, enqueuer):
    _, (vulnerability,) = await _seed(db_session, TENANT_B_ID)
    response = await tenant_client.post(_url(vulnerability), headers=superadmin_headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"queued": 1}
    assert enqueuer.calls == [(str(vulnerability.id), TENANT_B_ID, None)]
