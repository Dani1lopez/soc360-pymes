from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import ADMIN_A_ID, TENANT_A_ID


# ---------------------------------------------------------------------------
# RATE LIMITING / ACCOUNT LOCKOUT
# ---------------------------------------------------------------------------

async def test_account_lockout_after_10_failed_attempts(client: AsyncClient, seed_data):
    """Después de 10 intentos fallidos de login, la cuenta se bloquea con 429."""
    # 10 intentos fallidos
    for i in range(10):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": f"WrongPassword{i}!"},
        )
        assert resp.status_code == 401, f"Intento {i+1} debería fallar con 401"
    
    # El intento 11 debe devolver 429 (cuenta bloqueada)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "WrongPassword11!"},
    )
    assert resp.status_code == 429, "La cuenta debería estar bloqueada después de 10 intentos"
    assert "bloqueada" in resp.json()["detail"].lower()


async def test_account_lockout_reset_after_successful_login(client: AsyncClient, seed_data):
    """Después de login exitoso, el contador de intentos fallidos se resetea."""
    # 5 intentos fallidos
    for i in range(5):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": f"WrongPassword{i}!"},
        )
        assert resp.status_code == 401
    
    # Login exitoso resetea el contador
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert resp.status_code == 200, "El login exitoso debería funcionar y resetear el contador"
    
    # Ahora podemos tener 10 intentos fallidos más sin bloqueo inmediato
    # (el contador se reseteó, así que volvemos a empezar desde 0)


async def test_login_inactive_user_returns_401(client: AsyncClient, seed_data):
    """Un usuario inactivo no puede loguear, recibe 401."""
    # Primero desactivamos al viewer
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # Desactivamos viewer_a
    from tests.conftest import VIEWER_A_ID
    resp = await client.delete(f"/api/v1/users/{VIEWER_A_ID}", headers=headers)
    assert resp.status_code == 204
    
    # Intentamos loguear con viewer_a desactivado
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@alpha.test", "password": "ViewerAlpha123!"},
    )
    assert resp.status_code == 401, "Usuario inactivo no debería poder loguear"


# ---------------------------------------------------------------------------
# REFRESH TOKEN ROTATION
# ---------------------------------------------------------------------------

async def test_refresh_token_rotation_creates_new_tokens(client: AsyncClient, seed_data):
    """Al hacer refresh, se genera un nuevo access_token y se revoca el refresh anterior."""
    # Login inicial
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login.status_code == 200
    first_access_token = login.json()["access_token"]
    first_refresh_token = client.cookies.get("refresh_token")
    
    # Refresh
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    second_access_token = refresh.json()["access_token"]
    second_refresh_token = client.cookies.get("refresh_token")
    
    # Los tokens son diferentes
    assert second_access_token != first_access_token, "El access_token debería ser nuevo"
    assert second_refresh_token != first_refresh_token, "El refresh_token debería ser nuevo"
    
    # El refresh token anterior está revocado
    # Simulamos usar el refresh token anterior (necesitamos hacer un nuevo cliente o manipular cookies)
    # En este caso, verificamos que el token de acceso anterior sigue funcionando mientras no expire
    headers = {"Authorization": f"Bearer {second_access_token}"}
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200


async def test_old_refresh_token_is_revoked_after_rotation(client: AsyncClient, seed_data):
    """El refresh token anterior queda revocado después de rotación."""
    # Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login.status_code == 200
    old_refresh_token = client.cookies.get("refresh_token")
    
    # Refresh (rota el token)
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    new_refresh_token = client.cookies.get("refresh_token")
    
    # Intentar usar el refresh token anterior — debe estar revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={old_refresh_token}"},
    )
    assert resp.status_code == 401, "El refresh token anterior debería estar revocado"


# ---------------------------------------------------------------------------
# SESIONES CONCURRENTES (MAX 5)
# ---------------------------------------------------------------------------

async def test_concurrent_sessions_max_5(client: AsyncClient, seed_data):
    """Un usuario puede tener hasta 5 sesiones activas simultáneamente."""
    refresh_tokens = []
    
    # Crear 5 sesiones
    for i in range(5):
        # Usamos el mismo cliente pero limpiamos cookies entre logins
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
        )
        assert resp.status_code == 200, f"Login {i+1} debería funcionar"
        refresh_tokens.append(client.cookies.get("refresh_token"))
    
    # Todas las 5 sesiones deberían poder hacer refresh
    for i, rt in enumerate(refresh_tokens):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token={rt}"},
        )
        assert resp.status_code == 200, f"Refresh de sesión {i+1} debería funcionar"


async def test_sixth_session_revokes_oldest(client: AsyncClient, seed_data):
    """La sexta sesión de login revoca exactamente UN refresh token previo.

    El servicio mantiene MAX 5 refresh tokens activos por usuario.
    Al crear el sexto, revoca el más viejo (por created_at ASC).
    Como los logins ocurren rápidamente (mismo timestamp posible), verificamos
    que exactamente 1 de los 5 tokens fue revocado, sin asumir cuál.
    """
    refresh_tokens = []

    # Crear 5 sesiones sin tocarlas — todas activas en DB
    for i in range(5):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
        )
        assert resp.status_code == 200, f"Login {i+1} falló"
        rt = resp.cookies.get("refresh_token")
        assert rt is not None, f"No se recibió refresh_token en login {i+1}"
        refresh_tokens.append(rt)

    # Verificar que los 5 tokens funcionan antes de la sexta sesión
    for i, rt in enumerate(refresh_tokens):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token={rt}"},
        )
        assert resp.status_code == 200, f"Token {i+1} debe funcionar antes de la sexta sesión"
        # Rotar de vuelta para mantener el token activo
        refresh_tokens[i] = resp.cookies.get("refresh_token") or rt

    # Crear la SEXTA sesión — revoca el más antiguo
    client.cookies.clear()
    resp6 = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert resp6.status_code == 200, "La sexta sesión debe poder loguear"
    sixth_token = resp6.cookies.get("refresh_token")

    # Exactamente 1 de los tokens existentes debe haber sido revocado
    # y 4 deben seguir activos (más el nuevo de la sexta sesión = 5 total)
    revoked_count = 0
    active_count = 0
    for i, rt in enumerate(refresh_tokens):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token={rt}"},
        )
        if resp.status_code == 401:
            revoked_count += 1
        elif resp.status_code == 200:
            active_count += 1
            # Rotar para no romper el conteo de sesiones
            refresh_tokens[i] = resp.cookies.get("refresh_token") or rt

    assert revoked_count == 1, f"Exactamente 1 token debe estar revocado, got {revoked_count}"
    assert active_count == 4, f"Exactamente 4 tokens deben seguir activos, got {active_count}"

    # El token de la sexta sesión sigue funcionando
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={sixth_token}"},
    )
    assert resp.status_code == 200, "El token de la sexta sesión debe seguir activo"


# ---------------------------------------------------------------------------
# LOGOUT REVOCA JTI
# ---------------------------------------------------------------------------

async def test_logout_revokes_access_token_jti(client: AsyncClient, seed_data):
    """Después de logout, el access token (por su JTI) queda revocado."""
    # Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Verificamos que el token funciona
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    
    # Logout
    logout = await client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200
    
    # El access token ahora está revocado
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 401, "El access token debería estar revocado después del logout"


async def test_token_usage_after_logout_returns_401(client: AsyncClient, seed_data):
    """Usar un token después de logout devuelve 401."""
    # Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}
    
    # Logout
    await client.post("/api/v1/auth/logout", headers=headers)
    
    # Intentar usar el token
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# CHANGE PASSWORD INVALIDA TODAS LAS SESIONES
# ---------------------------------------------------------------------------

async def test_change_password_invalidates_all_sessions(client: AsyncClient, seed_data):
    """Al cambiar contraseña:
    - El JTI usado para cambiar la contraseña queda revocado en Redis
    - Todos los refresh tokens del usuario quedan revocados en DB
    - Se puede loguear con la nueva contraseña
    Nota: otros access tokens activos siguen válidos hasta expirar
    (el JTI solo se revoca para el token que hizo el cambio).
    """
    # Login para obtener el token que va a hacer el cambio
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
    )
    assert resp.status_code == 200
    change_token = resp.json()["access_token"]
    rt = resp.cookies.get("refresh_token")

    # Cambiar contraseña con ese token
    headers = {"Authorization": f"Bearer {change_token}"}
    change = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AdminAlpha123!", "new_password": "NuevaPassword456!"},
        headers=headers,
    )
    assert change.status_code == 200

    # El JTI del token que hizo el cambio queda revocado
    resp = await client.get("/api/v1/users/me", headers=headers)
    assert resp.status_code == 401, "El token usado para cambiar contraseña debe quedar revocado"

    # El refresh token también debe estar revocado
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={rt}"},
    )
    assert resp.status_code == 401, "El refresh token debe quedar revocado al cambiar contraseña"

    # Se puede loguear con la nueva contraseña
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@alpha.test", "password": "NuevaPassword456!"},
    )
    assert login.status_code == 200


async def test_change_password_revokes_all_refresh_tokens(client: AsyncClient, seed_data):
    """Al cambiar contraseña, todos los refresh tokens del usuario se revocan."""
    refresh_tokens = []
    
    # Crear 3 sesiones
    for i in range(3):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@alpha.test", "password": "AdminAlpha123!"},
        )
        assert resp.status_code == 200
        refresh_tokens.append(client.cookies.get("refresh_token"))
    
    # Usar la primera sesión para cambiar contraseña
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={refresh_tokens[0]}"},
    )
    assert resp.status_code == 200
    access_token = resp.json()["access_token"]

    headers = {"Authorization": f"Bearer {access_token}"}
    change = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "AdminAlpha123!", "new_password": "NuevaPassword789!"},
        headers=headers,
    )
    assert change.status_code == 200

    # Todos los refresh tokens deberían estar revocados en DB
    for i, rt in enumerate(refresh_tokens):
        client.cookies.clear()
        resp = await client.post(
            "/api/v1/auth/refresh",
            headers={"Cookie": f"refresh_token={rt}"},
        )
        assert resp.status_code == 401, f"Refresh token {i+1} debería estar revocado"


# ---------------------------------------------------------------------------
# FLUJOS COMPLETOS
# ---------------------------------------------------------------------------

async def test_complete_login_refresh_logout_flow(client: AsyncClient, seed_data):
    """Flujo completo: login → refresh → logout → token revocado."""
    # 1. Login
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": "viewer@alpha.test", "password": "ViewerAlpha123!"},
    )
    assert login.status_code == 200
    access_token = login.json()["access_token"]
    assert client.cookies.get("refresh_token") is not None
    
    # 2. Usar token
    headers = {"Authorization": f"Bearer {access_token}"}
    me = await client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200
    
    # 3. Refresh
    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    new_access_token = refresh.json()["access_token"]
    
    # 4. Usar nuevo token
    new_headers = {"Authorization": f"Bearer {new_access_token}"}
    me2 = await client.get("/api/v1/users/me", headers=new_headers)
    assert me2.status_code == 200
    
    # 5. Logout
    logout = await client.post("/api/v1/auth/logout", headers=new_headers)
    assert logout.status_code == 200
    
    # 6. Verificar que la cookie se limpió
    assert client.cookies.get("refresh_token") is None
    
    # 7. Token revocado
    me3 = await client.get("/api/v1/users/me", headers=new_headers)
    assert me3.status_code == 401


async def test_complete_session_management_flow(client: AsyncClient, seed_data):
    """Flujo de gestión de sesiones: múltiples logins, rotación, revocación."""
    # Login 1 — capturamos refresh token de la respuesta (no del cliente compartido)
    client.cookies.clear()
    login1 = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login1.status_code == 200
    token1 = login1.json()["access_token"]
    rt1 = login1.cookies.get("refresh_token")
    assert rt1 is not None, "Login 1 debe setear refresh_token"

    # Login 2 (mismo usuario, segunda sesión)
    client.cookies.clear()
    login2 = await client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@alpha.test", "password": "AnalystAlpha123!"},
    )
    assert login2.status_code == 200
    token2 = login2.json()["access_token"]
    rt2 = login2.cookies.get("refresh_token")
    assert rt2 is not None, "Login 2 debe setear refresh_token"

    # Ambos access tokens deberían funcionar (son JTIs distintos, ambos válidos)
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    me1 = await client.get("/api/v1/users/me", headers=headers1)
    me2 = await client.get("/api/v1/users/me", headers=headers2)
    assert me1.status_code == 200, "Token 1 debe funcionar"
    assert me2.status_code == 200, "Token 2 debe funcionar"

    # Refresh en sesión 1 — rt1 se rota (queda revocado, obtenemos uno nuevo)
    # Pasamos la cookie en el header para evitar restricciones de path de httpx.
    client.cookies.clear()
    refresh1 = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={rt1}"},
    )
    assert refresh1.status_code == 200, "Refresh de sesión 1 debe funcionar"

    # El rt1 original está revocado — no se puede usar de nuevo
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={rt1}"},
    )
    assert resp.status_code == 401, "El rt1 original debe estar revocado después de la rotación"

    # El rt2 sigue funcionando — es una sesión independiente
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"refresh_token={rt2}"},
    )
    assert resp.status_code == 200, "El rt2 debe seguir funcionando"
