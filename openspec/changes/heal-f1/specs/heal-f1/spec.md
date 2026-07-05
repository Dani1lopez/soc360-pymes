# Sanear F1 — Specification

## Propósito

Definir los requisitos formales para cerrar los issues conocidos de F1 antes de arrancar F2.

## Requisitos

### Requirement: Índices de usuario declarados en el modelo

El modelo `User` DEBE declarar los índices `ix_users_email_lower` (functional index sobre `lower(email)`) y `ix_users_tenant_active` (sobre `tenant_id, is_active`) en su `__table_args__` para que Alembic autogenerate no los detecte como "extra" y los elimine.

#### Scenario: Modelo declara ambos índices

- GIVEN el modelo `User` en `app/modules/users/models.py`
- WHEN se inspeccionan sus `__table_args__`
- THEN DEBE existir un `Index` para `ix_users_email_lower` sobre `func.lower(email)`
- AND DEBE existir un `Index` para `ix_users_tenant_active` sobre `tenant_id, is_active`

#### Scenario: Alembic autogenerate no detecta cambios en índices

- GIVEN la DB tiene los índices `ix_users_email_lower` y `ix_users_tenant_active`
- AND el modelo `User` declara ambos índices
- WHEN se ejecuta `alembic revision --autogenerate`
- THEN no DEBE generarse una migración que haga DROP de estos índices

### Requirement: last_login_at actualizado en login

El sistema DEBE actualizar `last_login_at` del usuario a la fecha/hora UTC actual en cada autenticación exitosa vía `login()`.

#### Scenario: Login exitoso actualiza last_login_at

- GIVEN un usuario activo con credenciales válidas
- WHEN se llama a `login()` con email y password correctos
- THEN `user.last_login_at` DEBE ser actualizado a `datetime.now(timezone.utc)`
- AND el cambio DEBE persistirse vía `db.flush()`

#### Scenario: Login fallido no actualiza last_login_at

- GIVEN un usuario activo con credenciales inválidas
- WHEN se llama a `login()` con password incorrecto
- THEN `last_login_at` NO DEBE ser modificado
- AND la función DEBE lanzar `AuthError`

### Requirement: Parámetro muerto request_headers eliminado

La función `login()` en `app/modules/auth/service.py` NO DEBE aceptar un parámetro `request_headers` — no se usa internamente ni lo pasa ningún caller.

#### Scenario: login() no acepta request_headers

- GIVEN la función `login()` en `app/modules/auth/service.py`
- WHEN se inspecciona su firma
- THEN NO DEBE existir el parámetro `request_headers`

#### Scenario: Callers existentes no se rompen

- GIVEN el router de auth llama a `service.login()`
- WHEN se ejecutan los tests de auth
- THEN todos los tests existentes DEBEN pasar

### Requirement: Archivos de tests API vacíos eliminados

El proyecto NO DEBE contener archivos de tests vacíos que den falsa sensación de cobertura.

#### Scenario: tests/api/ no contiene archivos vacíos

- GIVEN el directorio `tests/api/`
- WHEN se listan sus archivos
- THEN NO DEBEN existir `test_auth.py`, `test_tenants.py`, ni `test_users.py` con 0 líneas

### Requirement: Aserción específica en test_change_password_wrong_current

El test `test_change_password_wrong_current` DEBE verificar el código de estado exacto que el servicio devuelve (400), no un rango ambiguo.

#### Scenario: Test aserta 400 específico

- GIVEN el test `test_change_password_wrong_current` en `tests/test_auth.py`
- WHEN se ejecuta
- THEN DEBE asertar `resp.status_code == 400` (no `in (400, 401)`)

### Requirement: Rate limiting y CSRF documentados

El diseño de F1 DEBE documentar que:
- El rate limiting de login existe vía contador Redis + lockout (10 intentos / 15 min)
- La protección CSRF existe vía cookies `samesite:strict` + `X-Frame-Options: DENY` + security headers

#### Scenario: Rate limiting documentado

- GIVEN el design doc de heal-f1
- WHEN se lee la sección de rate limiting
- THEN DEBE describir el mecanismo de lockout Redis

#### Scenario: CSRF documentado

- GIVEN el design doc de heal-f1
- WHEN se lee la sección de CSRF
- THEN DEBE describir que la protección existe vía SameSite cookies + security headers
