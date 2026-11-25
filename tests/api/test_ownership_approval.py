"""H1/S1: a hand declaration waits for a superadmin approval.

``method="declaration"`` covers the assets no technical challenge can reach, so
recording it proves nothing by itself: it stays ``pending`` until a superadmin
approves it, and the approval records who approved and when. Only a superadmin
can approve, so a tenant admin cannot authorize their own claim.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import SUPERADMIN_ID, TENANT_A_ID

NOT_APPROVABLE = "ownership declaration cannot be approved"
NOTHING_PENDING = "no pending ownership declaration"
NOT_FOUND = "ownership declaration not found"
REVOKED = "ownership declaration is revoked"


async def _create_asset(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    value: str = "10.0.0.30",
    asset_type: str = "ip",
) -> str:
    response = await client.post(
        "/api/v1/assets/",
        headers=headers,
        json={"tenant_id": TENANT_A_ID, "type": asset_type, "value": value},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _declare(
    client: AsyncClient,
    headers: dict[str, str],
    asset_id: str,
    method: str = "declaration",
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=headers,
        json={"method": method},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _approve(client: AsyncClient, headers: dict[str, str], asset_id: str):
    return await client.post(
        f"/api/v1/assets/{asset_id}/ownership/approve", headers=headers
    )


async def test_a_declaration_is_pending_until_a_superadmin_approves_it(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    superadmin_headers: dict[str, str],
) -> None:
    """S1: recording a declaration authorizes nothing; the approval does."""
    asset_id = await _create_asset(tenant_client, admin_a_headers)

    declared = await _declare(tenant_client, admin_a_headers, asset_id)

    assert declared["method"] == "declaration"
    assert declared["status"] == "pending"
    assert declared["verified_at"] is None
    assert declared["approved_by_user_id"] is None
    assert declared["declared_by_user_id"] is not None

    approved = await _approve(tenant_client, superadmin_headers, asset_id)

    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["id"] == declared["id"]
    assert body["status"] == "verified"
    assert body["verified_at"] is not None
    assert body["approved_by_user_id"] == SUPERADMIN_ID
    assert body["declared_by_user_id"] == declared["declared_by_user_id"]

    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert listed.json()["items"][0]["status"] == "verified"
    assert listed.json()["items"][0]["approved_by_user_id"] == SUPERADMIN_ID


@pytest.mark.parametrize("role", ["admin", "analyst", "viewer"])
async def test_a_tenant_user_cannot_approve_a_declaration(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    analyst_a_headers: dict[str, str],
    viewer_a_headers: dict[str, str],
    role: str,
) -> None:
    """S1: a tenant admin cannot approve their own declaration."""
    caller = {
        "admin": admin_a_headers,
        "analyst": analyst_a_headers,
        "viewer": viewer_a_headers,
    }[role]
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.31")
    await _declare(tenant_client, admin_a_headers, asset_id)

    response = await _approve(tenant_client, caller, asset_id)

    assert response.status_code == 403, response.text
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert listed.json()["items"][0]["status"] == "pending"
    assert listed.json()["items"][0]["approved_by_user_id"] is None


@pytest.mark.parametrize(
    "method,asset_type,value",
    [
        ("dns_txt", "domain", "approve-dns.example"),
        ("http_file", "web_app", "http://10.0.0.32/app"),
    ],
)
async def test_a_challenge_declaration_cannot_be_approved_by_hand(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    superadmin_headers: dict[str, str],
    method: str,
    asset_type: str,
    value: str,
) -> None:
    """Only a challenge verifies dns_txt/http_file, so approving one is a 409."""
    asset_id = await _create_asset(
        tenant_client, admin_a_headers, value=value, asset_type=asset_type
    )
    await _declare(tenant_client, admin_a_headers, asset_id, method)

    response = await _approve(tenant_client, superadmin_headers, asset_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == NOT_APPROVABLE
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert listed.json()["items"][0]["status"] == "pending"


async def test_approving_an_asset_without_a_declaration_is_not_found(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    superadmin_headers: dict[str, str],
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.33")

    response = await _approve(tenant_client, superadmin_headers, asset_id)

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == NOT_FOUND


async def test_approving_an_unknown_asset_is_not_found(
    tenant_client: AsyncClient, superadmin_headers: dict[str, str]
) -> None:
    response = await _approve(tenant_client, superadmin_headers, str(uuid.uuid4()))

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "asset not found"


async def test_approving_a_revoked_declaration_is_a_conflict(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    superadmin_headers: dict[str, str],
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.34")
    await _declare(tenant_client, admin_a_headers, asset_id)
    revoked = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )
    assert revoked.status_code == 200, revoked.text

    response = await _approve(tenant_client, superadmin_headers, asset_id)

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == REVOKED


async def test_approving_an_already_verified_declaration_finds_nothing_pending(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    superadmin_headers: dict[str, str],
) -> None:
    """The approval is a one-shot transition, not an idempotent write."""
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.35")
    await _declare(tenant_client, admin_a_headers, asset_id)
    first = await _approve(tenant_client, superadmin_headers, asset_id)
    assert first.status_code == 200, first.text

    second = await _approve(tenant_client, superadmin_headers, asset_id)

    assert second.status_code == 404, second.text
    assert second.json()["detail"] == NOTHING_PENDING


async def test_verify_still_refuses_a_declaration(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    """S1 keeps the H2-T6 contract: only the approval verifies a declaration."""
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.36")
    await _declare(tenant_client, admin_a_headers, asset_id)

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/verify", headers=admin_a_headers
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "ownership declaration needs no verification"
