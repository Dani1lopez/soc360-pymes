from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import (
    TENANT_A_ID,
    TENANT_B_ID,
    SUPERADMIN_ID,
    ADMIN_A_ID,
    ANALYST_A_ID,
    VIEWER_A_ID,
    ADMIN_B_ID,
)


# ---------------------------------------------------------------------------
# GET /api/v1/users/me
# ---------------------------------------------------------------------------

async def test_get_me_superadmin(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get("/api/v1/users/me", headers=superadmin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == SUPERADMIN_ID
    assert data["is_superadmin"] is True
    assert data["tenant_id"] is None


async def test_get_me_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get("/api/v1/users/me", headers=admin_a_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == ADMIN_A_ID


async def test_get_me_analyst(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.get("/api/v1/users/me", headers=analyst_a_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "analyst"


async def test_get_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/users/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/users/
# ---------------------------------------------------------------------------

async def test_create_user_admin_ok(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "nuevo@alpha.test",
            "password": "Password123!",
            "full_name": "Nuevo Analyst",
            "role": "analyst",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    print("\n422 BODY:", resp.json()) 
    assert resp.status_code == 201
    assert resp.json()["email"] == "nuevo@alpha.test"
    assert resp.json()["tenant_id"] == TENANT_A_ID


async def test_create_user_superadmin_can_create_superadmin(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "nuevo_super@soc360.test",
            "password": "SuperPass123!",
            "full_name": "Nuevo Super",
            "role": "superadmin",
            "tenant_id": None,
            "is_superadmin": True,
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["is_superadmin"] is True


async def test_create_user_admin_cannot_create_superadmin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "fake_super@alpha.test",
            "password": "Password123!",
            "full_name": "Fake Super",
            "role": "superadmin",
            "tenant_id": None,
            "is_superadmin": True,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_create_user_admin_cannot_create_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "otro_admin@alpha.test",
            "password": "Password123!",
            "full_name": "Otro Admin",
            "role": "admin",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_create_user_admin_cross_tenant_forbidden(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "intruso@beta.test",
            "password": "Password123!",
            "full_name": "Intruso",
            "role": "viewer",
            "tenant_id": TENANT_B_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_create_user_analyst_forbidden(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "otro@alpha.test",
            "password": "Password123!",
            "full_name": "Otro",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_create_user_duplicate_email(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "analyst@alpha.test",  # ya existe
            "password": "Password123!",
            "full_name": "Copia",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 409


async def test_create_user_password_too_short(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "short@alpha.test",
            "password": "abc",
            "full_name": "Short",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 422


async def test_create_user_normal_without_tenant_id_rejected(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "sin_tenant@alpha.test",
            "password": "Password123!",
            "full_name": "Sin Tenant",
            "role": "viewer",
            "tenant_id": None,
            "is_superadmin": False,
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/users/
# ---------------------------------------------------------------------------

async def test_list_users_superadmin_sees_all(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get("/api/v1/users/", headers=superadmin_headers)
    assert resp.status_code == 200
    ids = [u["id"] for u in resp.json()]
    assert ADMIN_A_ID in ids
    assert ADMIN_B_ID in ids


async def test_list_users_admin_sees_own_tenant_only(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get("/api/v1/users/", headers=admin_a_headers)
    assert resp.status_code == 200
    for user in resp.json():
        assert user["tenant_id"] == TENANT_A_ID


async def test_list_users_admin_cannot_filter_other_tenant(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get(f"/api/v1/users/?tenant_id={TENANT_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_list_users_analyst_forbidden(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.get("/api/v1/users/", headers=analyst_a_headers)
    assert resp.status_code == 403


async def test_list_users_pagination(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get("/api/v1/users/?limit=1&offset=0", headers=admin_a_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_list_users_superadmin_filter_by_tenant(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get(f"/api/v1/users/?tenant_id={TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    for user in resp.json():
        assert user["tenant_id"] == TENANT_B_ID


# ---------------------------------------------------------------------------
# GET /api/v1/users/{user_id}
# ---------------------------------------------------------------------------

async def test_get_user_self(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.get(f"/api/v1/users/{ANALYST_A_ID}", headers=analyst_a_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == ANALYST_A_ID


async def test_get_user_admin_sees_own_tenant(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get(f"/api/v1/users/{ANALYST_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 200


async def test_get_user_admin_cross_tenant_forbidden(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_get_user_superadmin_any_tenant(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200


async def test_get_user_not_found(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000",
        headers=superadmin_headers,
    )
    assert resp.status_code == 404


async def test_get_user_viewer_cannot_see_other_user(client: AsyncClient, viewer_a_headers, seed_data):
    resp = await client.get(f"/api/v1/users/{ANALYST_A_ID}", headers=viewer_a_headers)
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PATCH /api/v1/users/{user_id}
# ---------------------------------------------------------------------------

async def test_patch_user_self_update_name(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"full_name": "Analyst Modificado"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Analyst Modificado"


async def test_patch_user_self_cannot_change_role(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"role": "admin"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_patch_user_self_cannot_change_is_active(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": False},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_patch_user_admin_updates_own_tenant_user(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"full_name": "Analyst Actualizado"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200


async def test_patch_user_admin_cannot_promote_to_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"role": "admin"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_patch_user_admin_cross_tenant_forbidden(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{ADMIN_B_ID}",
        json={"full_name": "Hack"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_patch_superadmin_cannot_self_deactivate(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/users/{SUPERADMIN_ID}",
        json={"is_active": False},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


async def test_patch_user_role_superadmin_rejected_by_schema(client: AsyncClient, superadmin_headers, seed_data):
    # UserUpdate rechaza role='superadmin' a nivel de schema
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"role": "superadmin"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_patch_user_not_found(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        "/api/v1/users/00000000-0000-0000-0000-000000000000",
        json={"full_name": "Ghost"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/users/{user_id}
# ---------------------------------------------------------------------------

async def test_deactivate_user_admin_ok(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 204


async def test_deactivate_user_self_forbidden(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.delete(f"/api/v1/users/{ADMIN_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 409


async def test_deactivate_user_cross_tenant_forbidden(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.delete(f"/api/v1/users/{ADMIN_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_deactivate_user_admin_cannot_deactivate_admin(client: AsyncClient, superadmin_headers, admin_a_headers, seed_data):
    # Un admin no puede desactivar a otro admin (mismo tenant)
    # Necesitamos un segundo admin en tenant A — lo creamos primero
    create_resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "admin2@alpha.test",
            "password": "AdminAlpha2123!",
            "full_name": "Admin Alpha 2",
            "role": "admin",  
            "tenant_id": TENANT_A_ID,
        },
        headers=superadmin_headers,
    )
    assert create_resp.status_code == 201
    new_admin_id = create_resp.json()["id"]
    resp = await client.delete(f"/api/v1/users/{new_admin_id}", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_deactivate_user_not_found(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.delete(
        "/api/v1/users/00000000-0000-0000-0000-000000000000",
        headers=admin_a_headers,
    )
    assert resp.status_code == 404


async def test_deactivate_user_analyst_forbidden(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=analyst_a_headers)
    assert resp.status_code == 403


async def test_deactivate_user_superadmin_ok(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=superadmin_headers)
    assert resp.status_code == 204


async def test_list_users_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/users/")
    assert resp.status_code == 401


async def test_get_user_unauthenticated(client: AsyncClient):
    resp = await client.get(f"/api/v1/users/{ANALYST_A_ID}")
    assert resp.status_code == 401


async def test_create_user_viewer_forbidden(client: AsyncClient, viewer_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "otro@alpha.test",
            "password": "Password123!",
            "full_name": "Otro",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=viewer_a_headers,
    )
    assert resp.status_code == 403


async def test_deactivated_user_cannot_login(
    client: AsyncClient, admin_a_headers, seed_data
):
    await client.delete(f"/api/v1/users/{ANALYST_A_ID}", headers=admin_a_headers)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert resp.status_code == 401