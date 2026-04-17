from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import TENANT_A_ID, TENANT_B_ID, ADMIN_B_ID


# ---------------------------------------------------------------------------
# POST /api/v1/tenants/
# ---------------------------------------------------------------------------

async def test_create_tenant_superadmin_ok(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Nueva Empresa", "slug": "nueva-empresa", "plan": "pro", "max_assets": 25},
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["slug"] == "nueva-empresa"
    assert data["plan"] == "pro"
    assert data["is_active"] is True


async def test_create_tenant_forbidden_for_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Intento", "slug": "intento-admin", "plan": "free", "max_assets": 5},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_create_tenant_forbidden_for_analyst(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Intento", "slug": "intento-analyst"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_create_tenant_unauthenticated(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Sin auth", "slug": "sin-auth"},
    )
    assert resp.status_code == 401


async def test_create_tenant_invalid_slug_uppercase(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Empresa", "slug": "Empresa-MAL"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_create_tenant_invalid_slug_spaces(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Empresa", "slug": "slug con espacios"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_create_tenant_slug_too_short(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Empresa", "slug": "ab"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_create_tenant_blank_name(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "   ", "slug": "nombre-vacio"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_create_tenant_duplicate_slug(client: AsyncClient, superadmin_headers, seed_data):
    # slug "empresa-alpha" ya existe en seed_data
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Otra Alpha", "slug": "empresa-alpha"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 409


async def test_create_tenant_max_assets_zero(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Empresa", "slug": "empresa-cero", "max_assets": 0},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/v1/tenants/
# ---------------------------------------------------------------------------

async def test_list_tenants_superadmin_sees_all(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get("/api/v1/tenants/", headers=superadmin_headers)
    assert resp.status_code == 200
    slugs = [t["slug"] for t in resp.json()]
    assert "empresa-alpha" in slugs
    assert "empresa-beta" in slugs


async def test_list_tenants_forbidden_for_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get("/api/v1/tenants/", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_list_tenants_pagination(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get("/api/v1/tenants/?offset=0&limit=1", headers=superadmin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_list_tenants_exclude_inactive(client: AsyncClient, superadmin_headers, seed_data):
    # Desactivamos tenant_b primero
    await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    resp = await client.get("/api/v1/tenants/?include_inactive=false", headers=superadmin_headers)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert TENANT_B_ID not in ids


async def test_list_tenants_include_inactive(client: AsyncClient, superadmin_headers, seed_data):
    await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    resp = await client.get("/api/v1/tenants/?include_inactive=true", headers=superadmin_headers)
    assert resp.status_code == 200
    ids = [t["id"] for t in resp.json()]
    assert TENANT_B_ID in ids


# ---------------------------------------------------------------------------
# GET /api/v1/tenants/{tenant_id}
# ---------------------------------------------------------------------------

async def test_get_tenant_superadmin_any_tenant(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == TENANT_A_ID


async def test_get_tenant_admin_own_tenant(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 200


async def test_get_tenant_admin_cross_tenant_returns_404(client: AsyncClient, admin_a_headers, seed_data):
    # Admin de tenant A no puede ver tenant B — devuelve 404 (no 403) para no revelar existencia
    resp = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 404


async def test_get_tenant_not_found(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.get(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000000",
        headers=superadmin_headers,
    )
    assert resp.status_code == 404


async def test_get_tenant_analyst_own_tenant(client: AsyncClient, analyst_a_headers, seed_data):
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=analyst_a_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# PATCH /api/v1/tenants/{tenant_id}
# ---------------------------------------------------------------------------

async def test_update_tenant_superadmin_ok(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "enterprise", "max_assets": 500},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "enterprise"
    assert resp.json()["max_assets"] == 500


async def test_update_tenant_forbidden_for_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "enterprise"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_update_tenant_not_found(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000000",
        json={"plan": "pro"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 404


async def test_update_tenant_blank_name_rejected(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"name": "   "},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


async def test_update_tenant_invalid_max_assets(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"max_assets": 0},
        headers=superadmin_headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /api/v1/tenants/{tenant_id}
# ---------------------------------------------------------------------------

async def test_deactivate_tenant_superadmin_ok(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 204

    # Verificar que está inactivo
    get_resp = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert get_resp.json()["is_active"] is False


async def test_deactivate_tenant_forbidden_for_admin(client: AsyncClient, admin_a_headers, seed_data):
    resp = await client.delete(f"/api/v1/tenants/{TENANT_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 403


async def test_deactivate_tenant_not_found(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.delete(
        "/api/v1/tenants/00000000-0000-0000-0000-000000000000",
        headers=superadmin_headers,
    )
    assert resp.status_code == 404


async def test_deactivate_already_inactive_tenant(client: AsyncClient, superadmin_headers, seed_data):
    await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    resp = await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Tests adicionales
# ---------------------------------------------------------------------------

async def test_list_tenants_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/v1/tenants/")
    assert resp.status_code == 401


async def test_get_tenant_unauthenticated(client: AsyncClient):
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}")
    assert resp.status_code == 401


async def test_list_tenants_forbidden_for_viewer(client: AsyncClient, viewer_a_headers, seed_data):
    resp = await client.get("/api/v1/tenants/", headers=viewer_a_headers)
    assert resp.status_code == 403


async def test_list_tenants_pagination_offset(client: AsyncClient, superadmin_headers, seed_data):
    resp1 = await client.get("/api/v1/tenants/?offset=0&limit=1", headers=superadmin_headers)
    resp2 = await client.get("/api/v1/tenants/?offset=1&limit=1", headers=superadmin_headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()[0]["id"] != resp2.json()[0]["id"]


async def test_update_tenant_plan_auto_adjusts_max_assets(client: AsyncClient, superadmin_headers, seed_data):
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "enterprise"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_assets"] == 500


async def test_deactivate_tenant_also_deactivates_users(client: AsyncClient, superadmin_headers, seed_data):
    await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
