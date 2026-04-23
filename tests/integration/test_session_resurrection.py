from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import (
    TENANT_A_ID,
    TENANT_B_ID,
    ANALYST_A_ID,
    ADMIN_B_ID,
)


# ---------------------------------------------------------------------------
# USER PATH: PATCH deactivation revokes tokens
# ---------------------------------------------------------------------------

async def test_patch_deactivate_user_revokes_access_token(
    client: AsyncClient, admin_a_headers, seed_data
):
    """PATCH con is_active=False revoca access token del usuario."""
    # 1. Login como analyst_a
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 2. Verificar que el token funciona
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200

    # 3. Admin desactiva analyst_a via PATCH
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": False},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # 4. Verificar que el access token fue revocado
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401, "Access token debe estar revocado tras PATCH deactivation"


async def test_patch_deactivate_user_revokes_refresh_token(
    client: AsyncClient, admin_a_headers, seed_data
):
    """PATCH con is_active=False revoca refresh token del usuario."""
    # 1. Login como analyst_a
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token is not None

    # 2. Admin desactiva analyst_a via PATCH
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": False},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200

    # 3. Verificar que el refresh token fue revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_token}"},
    )
    assert resp.status_code == 401, "Refresh token debe estar revocado tras PATCH deactivation"


# ---------------------------------------------------------------------------
# USER PATH: Reactivation does NOT resurrect old tokens
# ---------------------------------------------------------------------------

async def test_reactivation_does_not_resurrect_old_tokens(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Tras DELETE (deactivate) + PATCH (reactivate), tokens viejos siguen invalidos."""
    # 1. Login como analyst_a
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    old_access_token = login.json()["access_token"]
    old_refresh_token = login.cookies.get("refresh_token")

    # 2. Admin desactiva analyst_a via DELETE (revoca tokens)
    resp = await client.delete(
        f"/api/v1/users/{ANALYST_A_ID}",
        headers=admin_a_headers,
    )
    assert resp.status_code == 204

    # 3. Admin reactiva analyst_a via PATCH
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": True},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 4. Verificar que el old access token sigue revocado
    old_headers = {"Authorization": f"Bearer {old_access_token}"}
    resp = await client.get("/api/v1/users/me", headers=old_headers)
    assert resp.status_code == 401, "Old access token debe seguir revocado tras reactivacion"

    # 5. Verificar que el old refresh token sigue revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={old_refresh_token}"},
    )
    assert resp.status_code == 401, "Old refresh token debe seguir revocado tras reactivacion"

    # 6. Verificar que fresh login funciona
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200, "Fresh login debe funcionar tras reactivacion"


# ---------------------------------------------------------------------------
# TENANT PATH: PATCH deactivation revokes tokens
# ---------------------------------------------------------------------------

async def test_patch_deactivate_tenant_revokes_user_access_tokens(
    client: AsyncClient, superadmin_headers, seed_data
):
    """PATCH tenant con is_active=False revoca access tokens de sus usuarios."""
    # 1. Login como admin_b
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 2. Verificar que el token funciona
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200

    # 3. Superadmin desactiva tenant B via PATCH
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_B_ID}",
        json={"is_active": False},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    # 4. Verificar que el access token de admin_b fue revocado
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401, "Access token debe estar revocado tras tenant PATCH deactivation"


async def test_patch_deactivate_tenant_revokes_user_refresh_tokens(
    client: AsyncClient, superadmin_headers, seed_data
):
    """PATCH tenant con is_active=False revoca refresh tokens de sus usuarios."""
    # 1. Login como admin_b
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200
    refresh_token = login.cookies.get("refresh_token")
    assert refresh_token is not None

    # 2. Superadmin desactiva tenant B via PATCH
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_B_ID}",
        json={"is_active": False},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200

    # 3. Verificar que el refresh token fue revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_token}"},
    )
    assert resp.status_code == 401, "Refresh token debe estar revocado tras tenant PATCH deactivation"


# ---------------------------------------------------------------------------
# TENANT PATH: Reactivation does NOT resurrect old tokens
# ---------------------------------------------------------------------------

async def test_tenant_reactivation_does_not_resurrect_old_tokens(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Tras DELETE tenant (deactivate) + PATCH (reactivate), tokens viejos siguen invalidos."""
    # 1. Login como admin_b
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200
    old_access_token = login.json()["access_token"]
    old_refresh_token = login.cookies.get("refresh_token")

    # 2. Superadmin desactiva tenant B via DELETE
    resp = await client.delete(
        f"/api/v1/tenants/{TENANT_B_ID}",
        headers=superadmin_headers,
    )
    assert resp.status_code == 204

    # 3. Superadmin reactiva tenant B via PATCH
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_B_ID}",
        json={"is_active": True},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 4. Verificar que el old access token sigue revocado
    old_headers = {"Authorization": f"Bearer {old_access_token}"}
    resp = await client.get("/api/v1/users/me", headers=old_headers)
    assert resp.status_code == 401, "Old access token debe seguir revocado tras tenant reactivacion"

    # 5. Verificar que el old refresh token sigue revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={old_refresh_token}"},
    )
    assert resp.status_code == 401, "Old refresh token debe seguir revocado tras tenant reactivacion"

    # 6. Verificar que fresh login funciona
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200, "Fresh login debe funcionar tras tenant reactivacion"


# ---------------------------------------------------------------------------
# GUARD TESTS: No revocation on no-op PATCH or false->true reactivation
# ---------------------------------------------------------------------------

async def test_no_revocation_on_patch_without_is_active_change(
    client: AsyncClient, admin_a_headers, seed_data
):
    """PATCH que no cambia is_active NO debe revocar tokens."""
    # 1. Login como analyst_a
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 2. PATCH que solo cambia nombre (no is_active)
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"full_name": "Analyst Renamed"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200

    # 3. Verificar que el token sigue funcionando
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200, "Token debe seguir activo tras PATCH sin cambio de is_active"


async def test_no_revocation_on_false_to_true_user_reactivation(
    client: AsyncClient, admin_a_headers, seed_data
):
    """PATCH is_active=True sobre usuario ya inactivo NO debe revocar (no hay tokens que revocar)."""
    # 1. Desactivar analyst_a via DELETE
    resp = await client.delete(
        f"/api/v1/users/{ANALYST_A_ID}",
        headers=admin_a_headers,
    )
    assert resp.status_code == 204

    # 2. Reactivar via PATCH (false -> true)
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": True},
        headers=admin_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 3. Fresh login debe funcionar (no se revoco nada en la reactivacion)
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200, "Fresh login debe funcionar tras reactivacion"
    new_access_token = login.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_access_token}"}

    # 4. Verificar que el nuevo token funciona
    resp = await client.get("/api/v1/users/me", headers=new_headers)
    assert resp.status_code == 200


async def test_no_revocation_on_tenant_patch_without_is_active_change(
    client: AsyncClient, superadmin_headers, seed_data
):
    """PATCH tenant que no cambia is_active NO debe revocar tokens."""
    # 1. Login como admin_b
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # 2. PATCH que solo cambia plan (no is_active)
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_B_ID}",
        json={"plan": "starter"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200

    # 3. Verificar que el token sigue funcionando
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 200, "Token debe seguir activo tras tenant PATCH sin cambio de is_active"


async def test_no_revocation_on_false_to_true_tenant_reactivation(
    client: AsyncClient, superadmin_headers, seed_data
):
    """PATCH tenant is_active=True sobre tenant ya inactivo NO debe revocar."""
    # 1. Desactivar tenant B via DELETE
    resp = await client.delete(
        f"/api/v1/tenants/{TENANT_B_ID}",
        headers=superadmin_headers,
    )
    assert resp.status_code == 204

    # 2. Reactivar via PATCH (false -> true)
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_B_ID}",
        json={"is_active": True},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True

    # 3. Fresh login debe funcionar
    client.cookies.clear()
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert login.status_code == 200, "Fresh login debe funcionar tras tenant reactivacion"
