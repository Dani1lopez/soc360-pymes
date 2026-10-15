"""H2-T6: verifying the DNS TXT and HTTP file challenges over HTTP.

The challenge is satisfied by the asset owner publishing the token. Every
network call is overridden, so no test touches DNS or the web.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.modules.assets.ownership.router import (
    get_http_fetch,
    get_target_resolver,
    get_txt_lookup,
)
from tests.api.test_scans import _seed_asset
from tests.conftest import TENANT_A_ID

NOT_VERIFIED = "asset ownership is not verified"


@pytest.fixture
def challenge(tenant_client):
    """Fake DNS, HTTP and resolver; each test sets the answers it needs."""
    answers = SimpleNamespace(txt=[], body="", addresses=["10.0.0.7"])

    async def lookup(name: str) -> list[str]:
        return answers.txt

    async def fetch(url: str) -> str:
        return answers.body

    async def resolver(host: str) -> list[str]:
        return answers.addresses

    overrides = tenant_client.app.dependency_overrides
    overrides[get_txt_lookup] = lambda: lookup
    overrides[get_http_fetch] = lambda: fetch
    overrides[get_target_resolver] = lambda: resolver
    yield answers
    for dependency in (get_txt_lookup, get_http_fetch, get_target_resolver):
        overrides.pop(dependency, None)


async def _declare(
    client: AsyncClient, headers: dict[str, str], asset_id: str, method: str
) -> dict:
    response = await client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=headers,
        json={"method": method},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_dns_txt_challenge_verifies_and_records_the_fingerprint(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
) -> None:
    asset_id = await _seed_asset(
        db_session, "verify.example", tenant_id=TENANT_A_ID, asset_type="domain"
    )
    declaration = await _declare(tenant_client, admin_a_headers, asset_id, "dns_txt")
    assert declaration["status"] == "pending"
    challenge.txt = [f"soc360-verify={declaration['token']}"]

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "verified"
    assert body["verified_at"] is not None
    assert body["resolved_fingerprint"] == "10.0.0.7"


async def test_http_file_challenge_verifies(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
) -> None:
    asset_id = await _seed_asset(
        db_session,
        "http://10.0.0.4/app",
        tenant_id=TENANT_A_ID,
        asset_type="web_app",
    )
    declaration = await _declare(tenant_client, admin_a_headers, asset_id, "http_file")
    challenge.body = f"soc360-verify={declaration['token']}\n"

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"


@pytest.mark.parametrize("method", ["dns_txt", "http_file"])
async def test_a_missing_token_marks_the_declaration_failed(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
    method: str,
) -> None:
    asset_id = await _seed_asset(
        db_session, "verify-missing.example", tenant_id=TENANT_A_ID, asset_type="domain"
    )
    await _declare(tenant_client, admin_a_headers, asset_id, method)
    challenge.txt = ["soc360-verify=someone-else"]
    challenge.body = "soc360-verify=someone-else\n"

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "ownership challenge not satisfied"
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert listed.json()["items"][0]["status"] == "failed"


async def test_a_declaration_method_needs_no_verification(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
) -> None:
    asset_id = await _seed_asset(db_session, "10.0.0.11", tenant_id=TENANT_A_ID)
    await _declare(tenant_client, admin_a_headers, asset_id, "declaration")

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ownership declaration needs no verification"


async def test_a_revoked_declaration_cannot_be_verified(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
) -> None:
    asset_id = await _seed_asset(
        db_session, "verify-revoked.example", tenant_id=TENANT_A_ID, asset_type="domain"
    )
    await _declare(tenant_client, admin_a_headers, asset_id, "dns_txt")
    revoked = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )
    assert revoked.status_code == 200, revoked.text

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ownership declaration is revoked"


async def test_verifying_another_tenants_asset_is_not_found(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    admin_b_headers: dict[str, str],
    db_session,
    challenge: SimpleNamespace,
) -> None:
    asset_id = await _seed_asset(
        db_session, "verify-foreign.example", tenant_id=TENANT_A_ID, asset_type="domain"
    )
    await _declare(tenant_client, admin_a_headers, asset_id, "dns_txt")

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_b_headers
    )

    assert response.status_code == 404, response.text
