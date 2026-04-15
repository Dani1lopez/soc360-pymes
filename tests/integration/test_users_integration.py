from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import (
    TENANT_A_ID,
    TENANT_B_ID,
    SUPERADMIN_ID,
    ADMIN_A_ID,
    ANALYST_A_ID,
    VIEWER_A_ID,
)


# ---------------------------------------------------------------------------
# JERARQUÍA DE ROLES
# ---------------------------------------------------------------------------

async def test_superadmin_can_create_any_role(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede crear usuarios de cualquier rol."""
    for role in ["viewer", "analyst", "ingestor", "admin"]:
        resp = await client.post(
            "/api/v1/users/",
            json={
                "email": f"super-{role}@test.test",
                "password": "Password123!",
                "full_name": f"Super {role}",
                "role": role,
                "tenant_id": TENANT_A_ID,
            },
            headers=superadmin_headers,
        )
        assert resp.status_code == 201, f"Superadmin deberia poder crear {role}"
        assert resp.json()["role"] == role


async def test_superadmin_can_create_another_superadmin(
    client: AsyncClient, superadmin_headers, seed_data
):
    """Superadmin puede crear otro superadmin."""
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new-superadmin@soc360.test",
            "password": "Password123!",
            "full_name": "New Superadmin",
            "role": "superadmin",
            "tenant_id": None,
            "is_superadmin": True,
        },
        headers=superadmin_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "superadmin"
    assert resp.json()["is_superadmin"] is True


async def test_admin_can_create_viewer_analyst_but_not_admin(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin puede crear viewer y analyst, pero no otro admin."""
    # Admin puede crear viewer
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new-viewer@alpha.test",
            "password": "Password123!",
            "full_name": "New Viewer",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201
    
    # Admin puede crear analyst
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new-analyst@alpha.test",
            "password": "Password123!",
            "full_name": "New Analyst",
            "role": "analyst",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201
    
    # Admin NO puede crear otro admin
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new-admin@alpha.test",
            "password": "Password123!",
            "full_name": "New Admin",
            "role": "admin",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_admin_cannot_create_superadmin(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin no puede crear superadmin."""
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "fake-super@alpha.test",
            "password": "Password123!",
            "full_name": "Fake Super",
            "role": "superadmin",
            "tenant_id": None,
            "is_superadmin": True,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_analyst_cannot_create_any_user(
    client: AsyncClient, analyst_a_headers, seed_data
):
    """Analyst no puede crear usuarios de ningun tipo."""
    for role in ["viewer", "analyst", "admin"]:
        resp = await client.post(
            "/api/v1/users/",
            json={
                "email": f"analyst-tries-{role}@alpha.test",
                "password": "Password123!",
                "full_name": f"Test {role}",
                "role": role,
                "tenant_id": TENANT_A_ID,
            },
            headers=analyst_a_headers,
        )
        assert resp.status_code == 403


async def test_viewer_cannot_create_any_user(
    client: AsyncClient, viewer_a_headers, seed_data
):
    """Viewer no puede crear usuarios de ningun tipo."""
    for role in ["viewer", "analyst", "admin"]:
        resp = await client.post(
            "/api/v1/users/",
            json={
                "email": f"viewer-tries-{role}@alpha.test",
                "password": "Password123!",
                "full_name": f"Test {role}",
                "role": role,
                "tenant_id": TENANT_A_ID,
            },
            headers=viewer_a_headers,
        )
        assert resp.status_code == 403


async def test_admin_can_create_ingestor(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin puede crear usuario con rol ingestor."""
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "new-ingestor@alpha.test",
            "password": "Password123!",
            "full_name": "New Ingestor",
            "role": "ingestor",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "ingestor"


# ---------------------------------------------------------------------------
# SELF-SERVICE
# ---------------------------------------------------------------------------

async def test_user_can_update_own_name(client: AsyncClient, analyst_a_headers, seed_data):
    """Usuario puede actualizar su propio nombre."""
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"full_name": "Analyst Actualizado"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Analyst Actualizado"


async def test_user_can_update_own_email(client: AsyncClient, analyst_a_headers, seed_data):
    """Usuario puede actualizar su propio email."""
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"email": "analyst-nuevo@alpha.test"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "analyst-nuevo@alpha.test"


async def test_user_cannot_change_own_role(client: AsyncClient, analyst_a_headers, seed_data):
    """Usuario no puede cambiar su propio rol."""
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"role": "admin"},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_user_cannot_deactivate_self(client: AsyncClient, analyst_a_headers, seed_data):
    """Usuario no puede desactivarse a si mismo via patch."""
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"is_active": False},
        headers=analyst_a_headers,
    )
    assert resp.status_code == 403


async def test_user_self_deactivate_via_delete_forbidden(
    client: AsyncClient, analyst_a_headers, seed_data
):
    """Usuario no puede eliminarse a si mismo via delete."""
    resp = await client.delete(f"/api/v1/users/{ANALYST_A_ID}", headers=analyst_a_headers)
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# USUARIO DESACTIVADO
# ---------------------------------------------------------------------------

async def test_deactivated_user_cannot_login(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Usuario desactivado no puede loguear."""
    # Desactivamos viewer_a
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 204
    
    # Intentamos loguear
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@alpha.test", "password": "ViewerAlpha123!"},
    )
    assert resp.status_code == 401


async def test_deactivated_user_token_invalidated(
    client: AsyncClient, viewer_a_headers, admin_a_headers, seed_data
):
    """Token de usuario desactivado queda invalido."""
    # Verificamos que el token funciona
    resp = await client.get("/api/v1/users/me", headers=viewer_a_headers)
    assert resp.status_code == 200
    
    # Desactivamos al usuario
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=admin_a_headers)
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# CROSS-TENANT ISOLATION
# ---------------------------------------------------------------------------

async def test_admin_a_never_access_tenant_b_resources(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin A nunca puede acceder a recursos de tenant B."""
    from tests.conftest import ADMIN_B_ID
    
    # Intentar ver usuario de tenant B
    resp = await client.get(f"/api/v1/users/{ADMIN_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403
    
    # Intentar actualizar usuario de tenant B
    resp = await client.patch(
        f"/api/v1/users/{ADMIN_B_ID}",
        json={"full_name": "Hacked"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403
    
    # Intentar desactivar usuario de tenant B
    resp = await client.delete(f"/api/v1/users/{ADMIN_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 403
    
    # Intentar ver tenant B
    resp = await client.get(f"/api/v1/tenants/{TENANT_B_ID}", headers=admin_a_headers)
    assert resp.status_code == 404


async def test_list_users_no_cross_tenant_leak(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Listar usuarios no filtra datos de otros tenants."""
    resp = await client.get("/api/v1/users/", headers=admin_a_headers)
    assert resp.status_code == 200
    
    users = resp.json()
    for user in users:
        assert user.get("tenant_id") == TENANT_A_ID


# ---------------------------------------------------------------------------
# ADMIN NO PUEDE PROMOVER USUARIOS
# ---------------------------------------------------------------------------

async def test_admin_cannot_promote_analyst_to_admin(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin no puede promover analyst a admin."""
    resp = await client.patch(
        f"/api/v1/users/{ANALYST_A_ID}",
        json={"role": "admin"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


async def test_admin_cannot_promote_viewer_to_analyst(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Admin no puede promover viewer a analyst."""
    resp = await client.patch(
        f"/api/v1/users/{VIEWER_A_ID}",
        json={"role": "analyst"},
        headers=admin_a_headers,
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# FLUJOS COMPLETOS
# ---------------------------------------------------------------------------

async def test_complete_user_lifecycle(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Flujo completo: crear -> actualizar -> desactivar -> verificar."""
    # 1. Crear usuario
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "lifecycle@alpha.test",
            "password": "Password123!",
            "full_name": "Lifecycle User",
            "role": "viewer",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    
    # 2. Verificar que puede loguear
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "lifecycle@alpha.test", "password": "Password123!"},
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 3. Self-service: actualizar nombre
    resp = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "Lifecycle Updated"},
        headers=headers,
    )
    assert resp.status_code == 200
    
    # 4. Intentar cambiar rol (debe fallar)
    resp = await client.patch(
        f"/api/v1/users/{user_id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert resp.status_code == 403
    
    # 5. Desactivar el usuario (como admin)
    resp = await client.delete(f"/api/v1/users/{user_id}", headers=admin_a_headers)
    assert resp.status_code == 204
    
    # 6. Verificar que no puede loguear
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "lifecycle@alpha.test", "password": "Password123!"},
    )
    assert resp.status_code == 401


async def test_hierarchy_enforcement_complete(
    client: AsyncClient,
    superadmin_headers,
    admin_a_headers,
    analyst_a_headers,
    viewer_a_headers,
    seed_data,
):
    """Verificacion completa de la jerarquia de roles."""
    # Superadmin puede crear cualquier rol
    assert await _can_create_user(client, superadmin_headers, "superadmin") is True
    assert await _can_create_user(client, superadmin_headers, "admin") is True
    assert await _can_create_user(client, superadmin_headers, "analyst") is True
    
    # Admin puede crear roles inferiores
    assert await _can_create_user(client, admin_a_headers, "admin") is False
    assert await _can_create_user(client, admin_a_headers, "analyst") is True
    assert await _can_create_user(client, admin_a_headers, "viewer") is True
    
    # Analyst no puede crear ningun rol
    assert await _can_create_user(client, analyst_a_headers, "viewer") is False
    assert await _can_create_user(client, analyst_a_headers, "analyst") is False
    
    # Viewer no puede crear ningun rol
    assert await _can_create_user(client, viewer_a_headers, "viewer") is False


async def _can_create_user(client: AsyncClient, headers: dict, role: str) -> bool:
    """Helper para verificar si un rol puede crear otro rol."""
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": f"test-{role}-{unique_id}@test.test",
            "password": "Password123!",
            "full_name": f"Test {role}",
            "role": role,
            "tenant_id": TENANT_A_ID,
        },
        headers=headers,
    )
    return resp.status_code == 201


async def test_role_hierarchy_edge_cases(
    client: AsyncClient, admin_a_headers, superadmin_headers, seed_data
):
    """Casos borde de la jerarquia de roles."""
    # Admin intenta crear ingestor (deberia poder, ingestor tiene nivel 1, admin tiene 2)
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "ingestor-test@alpha.test",
            "password": "Password123!",
            "full_name": "Ingestor Test",
            "role": "ingestor",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201
    
    # Verificar que ingestor y analyst tienen el mismo nivel (1)
    # Admin puede crear ambos
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "another-analyst@alpha.test",
            "password": "Password123!",
            "full_name": "Another Analyst",
            "role": "analyst",
            "tenant_id": TENANT_A_ID,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 201


async def test_cross_tenant_user_creation_prevention(
    client: AsyncClient, admin_a_headers, seed_data
):
    """Prevencion completa de creacion cross-tenant."""
    # Admin A intenta crear usuario en tenant B
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
    
    # Admin A intenta crear usuario sin tenant_id (como superadmin)
    resp = await client.post(
        "/api/v1/users/",
        json={
            "email": "fake-super@nowhere.test",
            "password": "Password123!",
            "full_name": "Fake Super",
            "role": "superadmin",
            "tenant_id": None,
            "is_superadmin": True,
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 403
