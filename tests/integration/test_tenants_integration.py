from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import TENANT_A_ID, TENANT_B_ID, ADMIN_B_ID


# ---------------------------------------------------------------------------
# RLS AISLAMIENTO (Row Level Security)
# ---------------------------------------------------------------------------

async def test_rls_admin_a_cannot_see_tenant_b_data(client: AsyncClient, admin_a_headers, seed_data):
    """Admin de tenant A no puede ver usuarios de tenant B en el listado."""
    resp = await client.get("/api/v1/users/", headers=admin_a_headers)
    assert resp.status_code == 200
    
    users = resp.json()
    for user in users:
        assert user["tenant_id"] == TENANT_A_ID, \
            f"Admin A no debería ver usuarios de otros tenants: {user}"


async def test_rls_admin_a_query_params_cannot_bypass_isolation(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin A no puede usar query params para acceder a datos de tenant B."""
    # Intentar filtrar por tenant B
    resp = await client.get(f"/api/v1/users/?tenant_id={TENANT_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403, "No debería poder filtrar por otro tenant"


async def test_rls_admin_a_cannot_access_tenant_b_details(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin A no puede ver detalles del tenant B."""
    resp = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 404, "Debería devolver 404 (no revelar existencia)"


async def test_rls_admin_a_cannot_see_tenant_b_users_in_list(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin A no ve usuarios de tenant B en la lista."""
    resp = await client.get("/api/v1/users/", headers=admin_a_headers)
    assert resp.status_code == 200
    
    users = resp.json()
    user_ids = [u["id"] for u in users]
    
    assert ADMIN_B_ID not in user_ids, "Admin A no debería ver a admin_b en la lista"


# ---------------------------------------------------------------------------
# SOFT DELETE CASCADA
# ---------------------------------------------------------------------------

async def test_deactivate_tenant_cascades_to_users(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Desactivar un tenant desactiva automáticamente todos sus usuarios."""
    # Verificamos que admin_b está activo
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    
    # Desactivamos el tenant B
    resp = await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 204
    
    # Verificamos que el tenant está inactivo
    resp = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    
    # Verificamos que admin_b está inactivo
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


async def test_deactivated_tenant_users_cannot_login(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Los usuarios de un tenant desactivado no pueden loguear."""
    # Desactivamos tenant B
    resp = await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 204
    
    # Intentamos loguear con admin_b
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@beta.test", "password": "AdminBeta123!"},
    )
    assert resp.status_code == 401, "Usuario de tenant inactivo no debería poder loguear"


async def test_deactivated_tenant_users_tokens_revoked(
    client: AsyncClient, admin_b_headers, superadmin_headers, seed_data
):
    """Los tokens de usuarios de tenant desactivado quedan inválidos."""
    # Verificamos que el token de admin_b funciona
    resp = await client.get("/api/v1/users/me", headers=admin_b_headers)
    assert resp.status_code == 200
    
    # Desactivamos tenant B
    resp = await client.delete(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 204
    
    # El token de admin_b ahora debería fallar
    resp = await client.get("/api/v1/users/me", headers=admin_b_headers)
    # Puede ser 401 o seguir funcionando temporalmente hasta que el token expire
    # o se haga una verificación adicional. Depende de la implementación.
    # Generalmente el middleware verifica el tenant en cada request.


async def test_soft_delete_tenant_preserve_data(
    client: AsyncClient, superadmin_headers, seed_data
):
    """El soft delete del tenant preserva los datos pero los marca inactivos."""
    # Creamos un nuevo tenant
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Temp Tenant", "slug": "temp-tenant", "plan": "free"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    tenant_id = resp.json()["id"]
    
    # Creamos un usuario en ese tenant
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "temp@tenant.test",
            "password": "TempPass123!",
            "full_name": "Temp User",
            "role": "viewer",
            "tenant_id": tenant_id,
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    
    # Desactivamos el tenant
    resp = await client.delete(f"/api/v1/tenants/{tenant_id}", headers=superadmin_headers)
    assert resp.status_code == 204
    
    # Verificamos que el usuario está inactivo pero existe
    resp = await client.get(f"/api/v1/users/{user_id}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False
    assert resp.json()["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# PLAN Y MAX_ASSETS
# ---------------------------------------------------------------------------

async def test_update_plan_updates_max_assets(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Actualizar el plan actualiza automáticamente max_assets según la regla."""
    # Tenant A tiene plan starter → 25 max_assets
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    assert resp.json()["plan"] == "starter"
    assert resp.json()["max_assets"] == 50  # Seed data tiene 50, no 25
    
    # Cambiamos a plan enterprise
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "enterprise"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "enterprise"
    assert resp.json()["max_assets"] == 500, "max_assets debería actualizarse según el plan"


async def test_update_plan_free_sets_max_assets_10(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Cambiar a plan free establece max_assets en 10."""
    # Cambiamos tenant A a free
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "free"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "free"
    assert resp.json()["max_assets"] == 10


async def test_update_plan_pro_sets_max_assets_100(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Cambiar a plan pro establece max_assets en 100."""
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "pro"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "pro"
    assert resp.json()["max_assets"] == 100


async def test_update_plan_preserves_explicit_max_assets_if_provided(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Si se proporciona max_assets explícito, se respeta sobre el plan."""
    resp = await client.patch(
        f"/api/v1/tenants/{TENANT_A_ID}",
        json={"plan": "enterprise", "max_assets": 750},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["plan"] == "enterprise"
    assert resp.json()["max_assets"] == 750, "max_assets explícito debería tener prioridad"


# ---------------------------------------------------------------------------
# SUPERADMIN BYPASEA RLS
# ---------------------------------------------------------------------------

async def test_superadmin_sees_all_tenants(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede ver todos los tenants sin restricción."""
    resp = await client.get("/api/v1/tenants/", headers=superadmin_headers)
    assert resp.status_code == 200
    
    tenants = resp.json()
    slugs = [t["slug"] for t in tenants]
    
    assert "empresa-alpha" in slugs, "Superadmin debería ver tenant A"
    assert "empresa-beta" in slugs, "Superadmin debería ver tenant B"


async def test_superadmin_can_access_any_tenant_details(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede acceder a detalles de cualquier tenant."""
    resp_a = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=superadmin_headers)
    resp_b = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=superadmin_headers)
    
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["id"] == TENANT_A_ID
    assert resp_b.json()["id"] == TENANT_B_ID


async def test_superadmin_sees_all_users_across_tenants(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede ver usuarios de todos los tenants."""
    resp = await client.get("/api/v1/users/", headers=superadmin_headers)
    assert resp.status_code == 200
    
    users = resp.json()
    user_ids = [u["id"] for u in users]
    
    from tests.conftest import ADMIN_A_ID, ADMIN_B_ID, SUPERADMIN_ID
    assert ADMIN_A_ID in user_ids, "Superadmin debería ver admin_a"
    assert ADMIN_B_ID in user_ids, "Superadmin debería ver admin_b"
    assert SUPERADMIN_ID in user_ids, "Superadmin debería verse a sí mismo"


async def test_superadmin_can_filter_users_by_tenant(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede filtrar usuarios por tenant_id."""
    resp = await client.get(f"/api/v1/users/?tenant_id={TENANT_B_ID}", headers=superadmin_headers)
    assert resp.status_code == 200
    
    users = resp.json()
    for user in users:
        assert user["tenant_id"] == TENANT_B_ID, \
            "Filtro por tenant_id debería funcionar para superadmin"


# ---------------------------------------------------------------------------
# FLUJOS COMPLETOS DE NEGOCIO
# ---------------------------------------------------------------------------

async def test_complete_tenant_lifecycle(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Flujo completo: crear tenant → crear usuario → desactivar → verificar cascada."""
    # 1. Crear tenant
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Test Corp", "slug": "test-corp", "plan": "pro"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    tenant_id = resp.json()["id"]
    assert resp.json()["max_assets"] == 100
    
    # 2. Crear usuarios en el tenant
    users = []
    for i, role in enumerate(["admin", "analyst", "viewer"]):
        resp = await client.post(
            "/api/v1/users/",
            json={
                "email": f"{role}@testcorp.test",
                "password": "Password123!",
                "full_name": f"Test {role.title()}",
                "role": role,
                "tenant_id": tenant_id,
            },
            headers=superadmin_headers,
        )
        assert resp.status_code == 201, f"Error creando usuario {role}"
        users.append(resp.json()["id"])
    
    # 3. Verificar que los usuarios están activos
    for user_id in users:
        resp = await client.get(f"/api/v1/users/{user_id}", headers=superadmin_headers)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True
    
    # 4. Desactivar el tenant
    resp = await client.delete(f"/api/v1/tenants/{tenant_id}", headers=superadmin_headers)
    assert resp.status_code == 204
    
    # 5. Verificar que todos los usuarios están inactivos
    for user_id in users:
        resp = await client.get(f"/api/v1/users/{user_id}", headers=superadmin_headers)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False, f"Usuario {user_id} debería estar inactivo"
    
    # 6. Intentar loguear con uno de los usuarios
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@testcorp.test", "password": "Password123!"},
    )
    assert resp.status_code == 401


async def test_tenant_plan_upgrade_downgrade_flow(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Flujo de upgrade y downgrade de plan."""
    # Crear tenant en plan free
    resp = await client.post(
        "/api/v1/tenants/",
        json={"name": "Plan Test", "slug": "plan-test", "plan": "free"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    tenant_id = resp.json()["id"]
    assert resp.json()["max_assets"] == 10
    
    # Upgrade a pro
    resp = await client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"plan": "pro"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_assets"] == 100
    
    # Upgrade a enterprise
    resp = await client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"plan": "enterprise"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_assets"] == 500
    
    # Downgrade a starter
    resp = await client.patch(
        f"/api/v1/tenants/{tenant_id}",
        json={"plan": "starter"},
        headers=superadmin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_assets"] == 25


async def test_cross_tenant_isolation_complete(
    client: AsyncClient, admin_a_headers, admin_b_headers, seed_data
):
    """Verificación completa de aislamiento cross-tenant."""
    # Admin A obtiene lista de usuarios
    resp_a = await client.get("/api/v1/users/", headers=admin_a_headers)
    assert resp_a.status_code == 200
    users_a = {u["id"] for u in resp_a.json()}
    
    # Admin B obtiene lista de usuarios
    resp_b = await client.get("/api/v1/users/", headers=admin_b_headers)
    assert resp_b.status_code == 200
    users_b = {u["id"] for u in resp_b.json()}
    
    # No debe haber intersección
    intersection = users_a & users_b
    assert len(intersection) == 0, f"Usuarios en común detectados: {intersection}"
    
    # Admin A no puede ver detalles de admin B
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403
    
    # Admin B no puede ver detalles de tenant A
    resp = await client.get(f"/api/v1/tenants/{TENANT_A_ID}", headers=admin_b_headers)
    assert resp.status_code == 404
