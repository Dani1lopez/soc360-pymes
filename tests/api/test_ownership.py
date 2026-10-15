"""H2-T3: declaring, listing and revoking asset ownership over HTTP (S5/S6).

The declaration is the record that makes a scan legitimate, so the contract
pins who declared it, when, and that a foreign tenant cannot even see the asset.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import TENANT_A_ID


async def _create_asset(
    client: AsyncClient, headers: dict[str, str], value: str = "10.0.0.5"
) -> str:
    response = await client.post(
        "/api/v1/assets/",
        headers=headers,
        json={"tenant_id": TENANT_A_ID, "type": "ip", "value": value},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_declaring_records_who_and_when(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers)

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=admin_a_headers,
        json={"method": "declaration"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["asset_id"] == asset_id
    assert body["tenant_id"] == TENANT_A_ID
    assert body["method"] == "declaration"
    # S5: the declaration itself is the authorization where no technical check
    # is possible, so it is valid from the moment it is recorded.
    assert body["status"] == "verified"
    assert body["verified_at"] is not None
    assert body["declared_by_user_id"] is not None
    assert body["token"]
    assert body["created_at"]


async def _declare_and_list(
    client: AsyncClient, headers: dict[str, str], value: str
) -> None:
    asset_id = await _create_asset(client, headers, value=value)
    await client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=headers,
        json={"method": "declaration"},
    )

    response = await client.get(f"/api/v1/assets/{asset_id}/ownership", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["asset_id"] == asset_id
    assert body["items"][0]["status"] == "verified"


async def test_declared_state_is_listed_for_the_asset(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    await _declare_and_list(tenant_client, admin_a_headers, "10.0.0.6")


async def test_superadmin_sees_the_declared_state(
    tenant_client: AsyncClient, superadmin_headers: dict[str, str]
) -> None:
    await _declare_and_list(tenant_client, superadmin_headers, "10.0.0.16")


async def test_revoking_is_idempotent(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.7")
    await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=admin_a_headers,
        json={"method": "declaration"},
    )

    first = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )
    second = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "revoked"
    assert second.json()["status"] == "revoked"
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert [item["status"] for item in listed.json()["items"]] == ["revoked"]


async def test_revoking_withdraws_every_declaration_of_the_asset(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.9")
    for _ in range(2):
        await tenant_client.post(
            f"/api/v1/assets/{asset_id}/ownership",
            headers=admin_a_headers,
            json={"method": "declaration"},
        )

    revoked = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )

    assert revoked.status_code == 200, revoked.text
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_a_headers
    )
    assert [item["status"] for item in listed.json()["items"]] == ["revoked", "revoked"]


async def test_another_tenant_cannot_declare_or_read(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    admin_b_headers: dict[str, str],
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.8")

    declared = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=admin_b_headers,
        json={"method": "declaration"},
    )
    listed = await tenant_client.get(
        f"/api/v1/assets/{asset_id}/ownership", headers=admin_b_headers
    )
    revoked = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_b_headers
    )

    assert declared.status_code == 404, declared.text
    assert listed.status_code == 404, listed.text
    assert revoked.status_code == 404, revoked.text


async def test_a_challenge_method_starts_pending(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    """dns_txt and http_file are verified later, so they start pending (H2-T6)."""
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.11")

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=admin_a_headers,
        json={"method": "dns_txt"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["method"] == "dns_txt"
    assert body["status"] == "pending"
    assert body["verified_at"] is None
    assert body["token"]


async def test_viewers_cannot_declare_or_revoke(
    tenant_client: AsyncClient,
    admin_a_headers: dict[str, str],
    viewer_a_headers: dict[str, str],
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.9")

    declared = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership",
        headers=viewer_a_headers,
        json={"method": "declaration"},
    )
    revoked = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=viewer_a_headers
    )

    assert declared.status_code == 403, declared.text
    assert revoked.status_code == 403, revoked.text


async def test_revoking_without_a_declaration_is_not_found(
    tenant_client: AsyncClient, admin_a_headers: dict[str, str]
) -> None:
    asset_id = await _create_asset(tenant_client, admin_a_headers, value="10.0.0.10")

    response = await tenant_client.post(
        f"/api/v1/assets/{asset_id}/ownership/revoke", headers=admin_a_headers
    )

    assert response.status_code == 404, response.text
