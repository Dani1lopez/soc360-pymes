from __future__ import annotations

from httpx import AsyncClient


# ---------------------------------------------------------------------------
# LOGIN
# ---------------------------------------------------------------------------

async def test_login_superadmin_ok(client: AsyncClient, seed_data):
    """Login correcto devuelve 200 con access_token."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "superadmin@soc360.test", "password": "SuperAdmin123!"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert isinstance(body["expires_in"], int)
    assert body["expires_in"] > 0


async def test_login_admin_ok(client: AsyncClient, seed_data):
    """Login de admin de tenant devuelve token válido."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


async def test_login_wrong_password(client: AsyncClient, seed_data):
    """Contraseña incorrecta devuelve 401."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "WrongPassword999!"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client: AsyncClient, seed_data):
    """Email inexistente devuelve 401."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@nowhere.test", "password": "Whatever123!"},
    )
    assert resp.status_code == 401


async def test_login_invalid_email_format(client: AsyncClient, seed_data):
    """Email con formato inválido devuelve 422 (validación Pydantic)."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "not-an-email", "password": "Password123!"},
    )
    assert resp.status_code == 422


async def test_login_normalizes_email(client: AsyncClient, seed_data):
    """El email con mayúsculas y espacios se normaliza antes de buscar."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "  ADMIN@ALPHA.TEST  ", "password": "AdminAlpha123!"},
    )
    assert resp.status_code == 200


async def test_login_sets_refresh_cookie(client: AsyncClient, seed_data):
    """El login exitoso almacena la cookie refresh_token en el jar del cliente."""
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert resp.status_code == 200
    # Verificamos en client.cookies, que es donde httpx consolida el jar
    assert client.cookies.get("refresh_token") is not None


# ---------------------------------------------------------------------------
# REFRESH
# ---------------------------------------------------------------------------

async def test_refresh_ok(client: AsyncClient, seed_data):
    """Refresh con cookie válida devuelve un nuevo access_token distinto al original."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login.status_code == 200
    first_token = login.json()["access_token"]

    # httpx envía la cookie automáticamente porque path="/api/v1/auth" coincide
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    body = refresh.json()
    assert "access_token" in body
    assert body["access_token"] != first_token  # rotación de token


async def test_refresh_no_cookie(client: AsyncClient, seed_data):
    """Sin cookie de refresh devuelve 401."""
    # Cliente limpio, sin login previo → sin cookie en el jar
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# LOGOUT
# ---------------------------------------------------------------------------

async def test_logout_ok(client: AsyncClient, admin_a_headers: dict, seed_data):
    """Logout autenticado devuelve 200."""
    resp = await client.post("/api/v1/auth/logout", headers=admin_a_headers)
    assert resp.status_code == 200
    assert "detail" in resp.json()


async def test_logout_no_auth(client: AsyncClient, seed_data):
    """Logout sin token devuelve 401."""
    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 401


async def test_logout_clears_refresh_cookie(client: AsyncClient, seed_data):
    """Logout elimina la cookie refresh_token del jar del cliente."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200
    assert client.cookies.get("refresh_token") is None


async def test_token_invalidated_after_logout(client: AsyncClient, seed_data):
    """El access_token queda inválido tras el logout (revocado en la denylist de Redis)."""
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@alpha.test", "password": "ViewerAlpha123!"},
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    await client.post("/api/v1/auth/logout", headers=headers)

    # El mismo token ya no debe ser válido
    me_resp = await client.get("/api/v1/users/me", headers=headers)
    assert me_resp.status_code == 401


# ---------------------------------------------------------------------------
# CHANGE PASSWORD
# ---------------------------------------------------------------------------

async def test_change_password_ok(client: AsyncClient, admin_a_headers: dict, seed_data):
    """Cambio de contraseña correcto devuelve 200."""
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "AdminAlpha123!",
            "new_password": "NuevaContrasena456!",
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 200
    assert "detail" in resp.json()


async def test_change_password_wrong_current(
    client: AsyncClient,
    admin_a_headers: dict,
    seed_data,
):
    """Contraseña actual incorrecta devuelve 401."""
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "ContraseñaEquivocada999!",
            "new_password": "NuevaContrasena456!",
        },
        headers=admin_a_headers,
    )
    assert resp.status_code in (400, 401)


async def test_change_password_weak_new(
    client: AsyncClient,
    admin_a_headers: dict,
    seed_data,
):
    """Contraseña nueva débil falla con 422 (validación Pydantic en schema)."""
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "AdminAlpha123!",
            "new_password": "debil",
        },
        headers=admin_a_headers,
    )
    assert resp.status_code == 422


async def test_change_password_no_auth(client: AsyncClient, seed_data):
    """Change-password sin token devuelve 401."""
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": "AdminAlpha123!",
            "new_password": "NuevaContrasena456!",
        },
    )
    assert resp.status_code == 401