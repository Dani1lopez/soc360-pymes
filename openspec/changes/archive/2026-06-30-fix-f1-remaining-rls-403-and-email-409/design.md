# Design: fix-f1-remaining-rls-403-and-email-409

## 1. Architecture overview

El cambio introduce una nueva FastAPI dependency que hace el **cross-tenant pre-check** para endpoints que apuntan a usuarios, más una dependency paralela que hace lo mismo para endpoints que apuntan a tenants. Cada dependency eleva la DB session del request a contexto superadmin por la duración del SELECT, lee la fila target, compara `tenant_id` con el `tenant_id` del caller (para users) o compara el tenant id mismo con `current_user.tenant_id` (para tenants), después restaura el contexto de tenant del caller antes de que la función de servicio corra la mutación o read real. La capa de servicio queda libre de concerns de auth; confía en que la fila que se le pasa ya está autorizada para el caller.

El contrato 403 es uniforme cross endpoints de user-targeting y tenant-targeting: acceso cross-tenant siempre devuelve 403 (con un log line por intento bloqueado) y nunca 404. Esto unifica la señal de audit para que intentos cross-tenant sean indistinguibles de "fila genuinamente faltante" en la capa HTTP.

### Request flow (cross-tenant GET / PATCH / DELETE on users)

```
  Client
    |
    v
  Router (app/modules/users/router.py)
    |  1. extract current_user (Depends get_current_user)
    |  2. extract user_for_admin (NEW Depends get_user_for_admin_dep)
    |        |  -- SET LOCAL app.is_superadmin = 'true'
    |        |  -- SET LOCAL app.current_tenant = ''
    |        |  -- SELECT * FROM users WHERE id = :target_id
    |        |  -- compare target.tenant_id vs current_user.tenant_id
    |        |  -- on mismatch: log + raise HTTPException(403)
    |        |  -- restore: set_tenant_context(db, current_user.tenant_id, current_user.is_superadmin)
    |        v
    |     returns User row (or 403)
    v
  Service (app/modules/users/service.py)
    |  -- receives the pre-checked row
    |  -- runs the actual mutation / read
    |  -- no auth code in here
    v
  DB
```

### Request flow (cross-tenant GET on tenants)

```
  Client
    |
    v
  Router (app/modules/tenants/router.py)
    |  1. extract current_user (Depends get_current_user)
    |  2. extract tenant_for_admin (NEW Depends get_tenant_for_admin_dep)
    |        |  -- target_tenant_id != current_user.tenant_id (non-superadmin)
    |        |  -- compare (no SELECT needed: target id is the URL param)
    |        |  -- on mismatch: log + raise HTTPException(403)
    |        |  -- on match: SELECT * FROM tenants WHERE id = :target_id
    |        |     (row is reachable under caller's tenant context, RLS passes)
    |        |  -- if None: raise 404
    |        v
    |     returns Tenant row (or 403/404)
    v
  Service (app/modules/tenants/service.py)
    v
  DB
```

### Request flow (same-tenant GET / PATCH / DELETE on users)

```
  Client
    |
    v
  Router
    |  1. extract current_user
    |  2. extract user_for_admin via NEW Depends
    |        |  -- target.tenant_id == current_user.tenant_id
    |        |  -- no SET LOCAL needed, RLS already lets the SELECT through
    |        |  -- restore is a no-op (current context is already correct)
    |        v
    |     returns User row
    v
  Service -> DB
```

### Dónde se dispara cada cosa

- **403 raise site (users):** dentro de la nueva Depends `get_user_for_admin`, inmediatamente después de detectar el mismatch de `tenant_id`.
- **403 raise site (tenants):** dentro de la nueva Depends `get_tenant_for_admin`, cuando `target_tenant_id != current_user.tenant_id` y el caller no es superadmin.
- **Log line:** `logger.warning("cross_tenant_access_blocked", caller_id=..., target_id=..., method=..., endpoint=...)` en cada 403 raise site. El campo target id es el User id para la user Depends, el Tenant id para la tenant Depends.
- **RLS en juego para users same-tenant:** cada request same-tenant nunca toca elevación superadmin, así que RLS sigue siendo la única fuente de verdad para reads in-tenant.
- **RLS en juego para callers superadmin:** el path superadmin usa `get_user_internal` (sin pre-check), el SELECT corre bajo elevación superadmin que ya está seteada por `get_current_user` vía `set_tenant_context(... , True)`.
- **RLS en juego para tenants same-tenant:** leer el tenant id del propio caller está permitido por `rls_tenants` porque `id::text = current_setting('app.current_tenant', TRUE)` matchea; no se necesita elevación en ese caso. La Depends chequea el id de la URL contra `current_user.tenant_id` ANTES de emitir el SELECT así que la elevación superadmin solo se requiere para el path cross-tenant (y solo importa para users ahí — ver sección 3).

## 2. La nueva Depends

Vive en `app/dependencies.py`. Modelada sobre el bloque de elevación existente en `get_current_user` en `app/dependencies.py:90-93` (las dos llamadas `set_config(..., true)`) y sobre `get_db_with_tenant` en `app/dependencies.py:135-144` (misma shape: pull `current_user`, do work, yield/return).

### Signature — user Depends

```python
async def get_user_for_admin(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> User: ...
```

### Signature — tenant Depends

```python
async def get_tenant_for_admin(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> Tenant: ...
```

### Step-by-step behavior — get_user_for_admin

1. Leer `current_user` (ya validado, tiene `tenant_id` y `is_superadmin`).
2. Si `current_user.is_superadmin`: SELECT la fila bajo el contexto de tenant (ya superadmin) del caller. Sin elevación adicional. Devolver fila o elevar 404.
3. Si `current_user.tenant_id is None` y no es superadmin: imposible por invariante de `get_current_user`; 403 defensivo.
4. Si `current_user.tenant_id == user_id`'s tenant (la lectura requiere elevación porque el target puede estar en otro tenant): emitir `SELECT set_config('app.is_superadmin', 'true', true)` + `SELECT set_config('app.current_tenant', '', true)` (el par SET LOCAL de `app/dependencies.py:92-93`).
5. `SELECT * FROM users WHERE id = :user_id`. RLS ahora permite la fila sin importar el tenant.
6. Si la fila es None: restaurar contexto de tenant, elevar 404.
7. Comparar `row.tenant_id` con `current_user.tenant_id`. En mismatch: log + elevar 403 (mensaje `"Permisos insuficientes"`, en español según `app/modules/users/router.py:117`).
8. **Siempre restaurar contexto de tenant** vía `await set_tenant_context(db, current_user.tenant_id, current_user.is_superadmin)` antes de devolver la fila. Esto re-establece el contexto canónico del caller para la mutación de capa de servicio que sigue. (Incluso si los pasos 4-6 elevan, el SET LOCAL garantiza que la elevación se limpia en el próximo COMMIT/ROLLBACK; el restore explícito es belt-and-suspenders para el happy path.)
9. Devolver la fila.

### Step-by-step behavior — get_tenant_for_admin

1. Leer `current_user`.
2. Si `current_user.is_superadmin`: SELECT la fila bajo el contexto de tenant del caller. Sin elevación adicional. Devolver fila o elevar 404.
3. Si `current_user.tenant_id is None` y no es superadmin: imposible por invariante; 403 defensivo.
4. **Comparar `tenant_id` (URL param) con `current_user.tenant_id`** ANTES de cualquier SELECT. Esta es la inversión de la user Depends: el target de comparación es el id de la URL mismo, no el `tenant_id` column de una fila. Los dos son el mismo concepto — el id de la URL ES el tenant id que estamos chequeando.
5. En mismatch: log + elevar 403 (mensaje `"Permisos insuficientes"`, en español, matcheando la user Depends y `app/dependencies.py:160`). **No se performa DB SELECT** — el pre-check dispara en Python antes de tocar la DB.
6. En match: SELECT `* FROM tenants WHERE id = :tenant_id`. Bajo el contexto de tenant del caller, RLS deja pasar esto (la policy es `id::text = current_setting('app.current_tenant', TRUE)`). Si None: elevar 404. Devolver fila.
7. Devolver la fila.

**Por qué no elevación RLS para el caso tenant cross-tenant:** la comparación corre en Python antes del SELECT, así que nunca necesitamos leer una fila que el contexto de tenant del caller oculta. Esto es más eficiente que el path de la user Depends (un par `set_config` extra se ahorra en el caso 403 cross-tenant) e igualmente correcto. La user Depends necesita elevación solo porque el pre-check debe mirar una fila cuya existencia y `tenant_id` column son ambos desconocidos hasta que el SELECT corre.

### SET LOCAL semantics

El tercer argumento `true` a `set_config` produce un `SET LOCAL` (setting transaction-local). Se revierte automáticamente en `COMMIT` o `ROLLBACK`. Esto significa:

- Un request distinto que reuse la misma conexión pooled no puede ver el estado elevado.
- Una excepción elevada dentro del bloque de elevación deja la sesión fallida; la siguiente operación dispara ROLLBACK y el SET LOCAL se limpia.
- Igual llamamos `set_tenant_context` explícitamente después para ser defensivos y re-establecer el contexto de request canónico para la mutación.

### Code pattern (skeleton, NOT full implementation) — get_user_for_admin

```python
# app/dependencies.py — appended after get_db_with_tenant
async def get_user_for_admin(
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> User:
    # Superadmin path: row is already visible under the elevated session
    # established by get_current_user + get_db_with_tenant.
    if current_user.is_superadmin:
        row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        return row

    # Non-superadmin: elevate to read the cross-tenant row (modeled on
    # app/dependencies.py:90-93 — the SET LOCAL pair inside get_current_user).
    await db.execute(text("SELECT set_config('app.is_superadmin', 'true', true)"))
    await db.execute(text("SELECT set_config('app.current_tenant', '', true)"))
    try:
        row = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    finally:
        # Always restore — SET LOCAL is cleared on COMMIT/ROLLBACK, but
        # we re-set the canonical context so the next statement in the
        # request runs under the caller's tenant.
        await set_tenant_context(db, current_user.tenant_id, False)

    if row is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if row.tenant_id != current_user.tenant_id:
        logger.warning(
            "cross_tenant_access_blocked",
            caller_id=str(current_user.id),
            target_id=str(user_id),
            method="GET",  # filled by caller (see router pattern below)
            endpoint=f"/users/{user_id}",
        )
        raise HTTPException(status_code=403, detail="Permisos insuficientes")
    return row
```

### Code pattern (skeleton, NOT full implementation) — get_tenant_for_admin

```python
# app/dependencies.py — appended after get_user_for_admin
async def get_tenant_for_admin(
    tenant_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_with_tenant),
) -> Tenant:
    # Superadmin path: caller is already elevated, no extra work.
    if current_user.is_superadmin:
        row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Tenant no encontrado")
        return row

    # Non-superadmin: pre-check the URL id against caller's tenant_id BEFORE
    # touching the DB. The id is the comparison key, so no SELECT is needed
    # to discover the target's tenant.
    if current_user.tenant_id is None:
        # Defensive: get_current_user guarantees this is unreachable, but
        # we mirror the same defensive branch as get_user_for_admin.
        raise HTTPException(status_code=403, detail="Permisos insuficientes")

    if tenant_id != current_user.tenant_id:
        logger.warning(
            "cross_tenant_access_blocked",
            caller_id=str(current_user.id),
            target_id=str(tenant_id),  # tenant id, not user id
            method="GET",               # filled by router wrapper
            endpoint=f"/tenants/{tenant_id}",
        )
        raise HTTPException(status_code=403, detail="Permisos insuficientes")

    # Same-tenant path: RLS lets the SELECT through under the caller's tenant.
    row = (await db.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")
    return row
```

### Router pattern (the method/endpoint hint)

Los campos `method` y `endpoint` del log necesitan el verbo HTTP y el path. Dos opciones:

- **Opción A (elegida):** envolver la dependency en un factory pequeño que los capture. Añadir `get_user_for_admin_get`, `get_user_for_admin_patch`, `get_user_for_admin_delete` como wrappers de una línea que llaman al helper core con el valor correcto de `method=`. El endpoint path es un string constante por router. Mismo factory para tenants: `get_tenant_for_admin_get`.
- **Opción B:** leer `request: Request = Depends(...)` dentro de la dependency y extraer `request.method` / `request.url.path`. Ahorra wrappers pero acopla la dependency al FastAPI `Request` object y hace la dependency más difícil de unit-testear.

Tradeoff: Opción A son unos pocos wrappers triviales de una línea pero mantiene la dependency pure-typed y unit-testable. Opción B son menos líneas pero más difícil de testear (hay que fakear un `Request`).

**Decisión:** Opción A. El costo son un puñado de wrappers de 3 líneas; los unit tests pueden driver el helper subyacente directamente.

```python
# app/dependencies.py
def _user_for_admin(method: str):
    async def _dep(
        user_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_with_tenant),
    ) -> User:
        return await _get_user_for_admin(user_id, current_user, db, method=method, endpoint=f"/users/{user_id}")
    return _dep

get_user_for_admin_get = _user_for_admin("GET")
get_user_for_admin_patch = _user_for_admin("PATCH")
get_user_for_admin_delete = _user_for_admin("DELETE")

def _tenant_for_admin(method: str):
    async def _dep(
        tenant_id: uuid.UUID,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_with_tenant),
    ) -> Tenant:
        return await _get_tenant_for_admin(tenant_id, current_user, db, method=method, endpoint=f"/tenants/{tenant_id}")
    return _dep

# Tenants only have one targeted endpoint (GET /tenants/{id}) in PR-A.
# PATCH and DELETE on tenants remain superadmin-only and do not need the
# cross-tenant pre-check (the superadmin branch already covers them).
get_tenant_for_admin_get = _tenant_for_admin("GET")
```

## 3. Cambios en capa de servicio

### Para users (`app/modules/users/service.py`)

#### `get_user_for_admin`

```python
async def get_user_for_admin(
    current_user: User,
    target_id: uuid.UUID,
    db: AsyncSession,
) -> User:
    """Pre-checked user read for admin endpoints.

    Caller (a Depends) has already elevated the session and verified
    that the target row's tenant_id matches current_user.tenant_id.
    This function is a thin wrapper for symmetry with get_user_internal
    and to keep the router signature uniform.

    Raises UserError(404) if the row has vanished between the pre-check
    SELECT and this call (TOCTOU window, very rare).
    """
    row = (await db.execute(select(User).where(User.id == target_id))).scalar_one_or_none()
    if row is None:
        raise UserError("Usuario no encontrado", status_code=404)
    return row
```

#### `get_user_internal`

```python
async def get_user_internal(
    target_id: uuid.UUID,
    db: AsyncSession,
) -> User | None:
    """System/superadmin read. NO pre-check.

    Trusts the caller — used by the superadmin branch of the new Depends
    and by any future system-level code (background jobs, admin tools).
    """
    return (await db.execute(select(User).where(User.id == target_id))).scalar_one_or_none()
```

#### `update_user` rewrite

```python
async def update_user(
    current_user: User,
    target: User,           # pre-checked by the Depends
    data: UserUpdate,
    db: AsyncSession,
    redis: Redis,
) -> User:
    """Update a pre-checked user row.

    The router passes in the User row already validated by
    get_user_for_admin. This function is now auth-clean: it only
    applies field changes and (if deactivating) revokes tokens.
    """
    # The self-409 and admin-modifies-superadmin checks move to the
    # router (they were already there in router.py:140-175 and stay there).
    update_data = data.model_dump(exclude_unset=True)
    # ... existing field-application logic, unchanged ...
    await db.flush()
    # ... existing token-revocation logic, unchanged ...
    await db.refresh(target)
    return target
```

#### `deactivate_user` rewrite

```python
async def deactivate_user(
    current_user: User,
    target: User,           # pre-checked by the Depends
    db: AsyncSession,
    redis: Redis,
) -> None:
    """Deactivate a pre-checked user row. Auth-clean."""
    if not target.is_active:
        raise UserError("El usuario ya está desactivado", status_code=409)
    target.is_active = False
    await db.flush()
    # ... existing token-revocation logic, unchanged ...
```

#### `_log_cross_tenant_attempt` helper

```python
def _log_cross_tenant_attempt(
    caller_id: uuid.UUID,
    target_id: uuid.UUID,
    method: str,
    endpoint: str,
) -> None:
    """Single chokepoint for the 403 log line (OQ-1).

    The same helper covers both user-targeting and tenant-targeting
    attempts: `target_id` is whichever id the pre-check operated on
    (a user id for the user Depends, a tenant id for the tenant Depends).
    """
    logger.warning(
        "cross_tenant_access_blocked",
        caller_id=str(caller_id),
        target_id=str(target_id),
        method=method,
        endpoint=endpoint,
        # NO tenant_id: sensitive info avoidance (OQ-1)
    )
```

Llamado desde la nueva Depends en el momento en que se detecta el mismatch. Ya no hay un helper de tenant separado — ambas Depends comparten el mismo chokepoint porque los campos del log son idénticos excepto por el valor de `target_id`.

#### Router signature después del rewrite

```python
# app/modules/users/router.py

@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user: User = Depends(get_user_for_admin_get),  # pre-checked
    # db removed — Depends already has it
) -> User:
    return user

@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    body: UserUpdate,
    current_user: CurrentUserDep,
    user: User = Depends(get_user_for_admin_patch),  # pre-checked
    db: DBWithTenantDep,
    redis: RedisDep,
) -> User:
    # The existing in-router checks (self-deactivation 409, admin-modifies-superadmin
    # 403, role hierarchy 403) STAY HERE — they are policy rules, not tenant rules.
    if current_user.is_superadmin and user.id == current_user.id and body.is_active is False:
        raise HTTPException(status_code=409, detail="No puedes desactivarte a ti mismo")
    # ... existing role/admin checks, unchanged ...
    updated = await service.update_user(current_user=current_user, target=user, data=body, db=db, redis=redis)
    # ...

@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user: User = Depends(get_user_for_admin_delete),  # pre-checked
    current_user: AdminDep,
    db: DBWithTenantDep,
    redis: RedisDep,
) -> None:
    if user.id == current_user.id:
        raise HTTPException(status_code=409, detail="No puedes desactivarte a ti mismo")
    # ... existing admin-vs-admin check, unchanged ...
    await service.deactivate_user(current_user=current_user, target=user, db=db, redis=redis)
    # ...
```

### Para tenants (`app/modules/tenants/router.py`)

La decisión de diseño (RK-6) es **unificar el contrato 403 cross user y tenant endpoints**: reads cross-tenant sobre `/tenants/{id}` DEBEN también devolver 403, no 404. La Depends de arriba (`get_tenant_for_admin`) implementa esto. PATCH y DELETE sobre tenants quedan superadmin-only y no necesitan el pre-check (el `SuperadminDep` existente es la gate).

#### Tenant router rewrite

```python
# app/modules/tenants/router.py

@router.get(
    "/{tenant_id}",
    response_model=schemas.TenantResponse,
    summary="Obtener tenant por id",
)
async def get_tenant(
    current_user: CurrentUserDep,
    tenant: Tenant = Depends(get_tenant_for_admin_get),  # pre-checked
) -> schemas.TenantResponse:
    return schemas.TenantResponse.model_validate(tenant)
```

El viejo check inline en `tenants/router.py:64-66` (que elevaba 404 para non-superadmin cross-tenant) se REMUEVE — la Depends ahora hace el mismo check y devuelve 403 en su lugar. El viejo path 404 en `tenants/router.py:71-76` (que elevaba 404 cuando RLS ocultaba la fila) también se REMUEVE — el SELECT de la Depends corre bajo el contexto de tenant del caller (caso same-tenant) o se skipea enteramente (caso cross-tenant, la Depends devuelve 403 primero), así que el único 404 legítimo es cuando `current_user.tenant_id == tenant_id` pero la fila de tenant no existe (imposible por la FK constraint que users tienen sobre `tenants.id`, pero la Depends lo cubre por seguridad).

**Test update required:** `tests/integration/test_tenants_integration.py:406` DEBE actualizarse de `assert resp.status_code == 404` a `assert resp.status_code == 403`. Esto está in scope para PR-A según la decisión RK-6.

#### Qué NO cambia para tenants

- `POST /tenants/` (create) — superadmin only, no pre-check necesario.
- `GET /tenants/` (list) — superadmin only, no pre-check necesario.
- `PATCH /tenants/{id}` y `DELETE /tenants/{id}` — superadmin only, el `SuperadminDep` existente es suficiente.
- La capa de servicio `get_tenant_by_id`, `update_tenant`, `deactivate_tenant` — quedan auth-clean. La Depends maneja el caso cross-tenant para GET; los otros endpoints son superadmin-only a nivel de router.

## 4. PR-B design (email 409)

En `app/modules/users/service.py:create_user`, envolver `db.flush()` en un try/except que traduzca `IntegrityError` con `pgcode == '23505'` a `UserError(409)`.

### Bloque try/except exacto

```python
# app/modules/users/service.py — create_user, around line 67

db.add(user)
try:
    await db.flush()
except IntegrityError as exc:
    # asyncpg-specific: e.orig.pgcode is '23505' for unique_violation,
    # '23503' for FK violation, '23514' for check violation.
    # Pin asyncpg in the dependency manifest (RK-3 mitigation).
    if getattr(exc.orig, "pgcode", None) == "23505":
        await db.rollback()  # clear failed session state (R09)
        raise UserError("El email ya está registrado", status_code=409) from exc
    raise  # other IntegrityError variants propagate unchanged (R08)
await db.refresh(user)
return user
```

### Dónde se ubica el rollback

Después del `except IntegrityError` y ANTES del `raise UserError(...)`. El orden importa: la sesión de SQLAlchemy está en estado fallido tras un flush que pegó una UNIQUE constraint, y cualquier `db.execute` subsiguiente elevaría `PendingRollbackError`. Necesitamos limpiar ese estado antes de re-elevar la excepción user-facing para que el router pueda hacer trabajo de seguimiento (no lo hará, pero el global exception handler podría loguear metadata vía queries adicionales).

### Cómo funciona el path del test

`test_users_integration.py:527` (`test_email_unique_globally_returns_409`):

1. Primer POST con `email=duplicate@test.test` en tenant A → 201 (pre-check pasa, INSERT tiene éxito).
2. Segundo POST con el mismo `email` (cualquier tenant) → pre-check lo captura → 409 (este path ya funciona hoy vía `_is_email_taken`).
3. (Implícito) El path de race condition: dos POSTs concurrentes ambos pasan el pre-check, el segundo pega la DB UNIQUE constraint, el handler de IntegrityError devuelve 409.

El nuevo path de código cubre el paso 3, que el test no ejercita directamente pero es la razón del cambio. El pre-check sigue cubriendo el paso 2. No se necesitan cambios de test para PR-B en la capa de integración; el test existente pasa por el pre-check hoy y seguirá pasando tras el refactor (el nuevo handler es no-op cuando el pre-check ya capturó el duplicado).

## 5. Test design

### PR-A — unit tests en `tests/unit/test_dependencies.py` (o `tests/unit/test_users_service.py`)

- `test_log_cross_tenant_attempt_includes_required_fields` — assert la log call tiene caller_id, target_id, method, endpoint, no tenant_id.
- `test_get_user_for_admin_returns_row_on_match` — same tenant, devuelve la fila.
- `test_get_user_for_admin_raises_403_on_tenant_mismatch` — non-superadmin, target en otro tenant, eleva 403.
- `test_get_user_for_admin_returns_row_for_superadmin` — superadmin caller, target en cualquier tenant, devuelve la fila.
- `test_get_user_for_admin_raises_404_on_missing_row` — id no existente, eleva 404.
- `test_get_user_internal_does_not_pre_check` — system path, target en otro tenant, sin error (devuelve fila).
- `test_update_user_does_not_call_flush_on_403` — patchear el target en otro tenant no debe mutar la DB. (Drives el nuevo Depends path.)
- `test_deactivate_user_does_not_call_flush_on_403` — mismo para DELETE.

### PR-A — unit tests para la tenants Depends en `tests/unit/test_dependencies.py` (o `tests/unit/test_tenants_service.py`)

- `test_get_tenant_for_admin_returns_own_tenant` — non-superadmin, propio tenant_id, devuelve fila.
- `test_get_tenant_for_admin_returns_403_for_cross_tenant` — non-superadmin, otro tenant_id, eleva 403 (NO 404 — este es el cambio de contrato decidido por el usuario).
- `test_get_tenant_for_admin_returns_row_for_superadmin` — superadmin, cualquier tenant_id, devuelve fila.
- `test_get_tenant_for_admin_raises_404_on_missing_row_when_same_tenant` — non-superadmin, propio tenant_id, fila genuinamente ausente, eleva 404 (defensivo — FK hace difícil llegar, pero la Depends lo cubre).
- `test_get_tenant_for_admin_emits_log_line_on_cross_tenant` — assert `cross_tenant_access_blocked` log con caller_id, target_id (= tenant id), method, endpoint, no tenant_id.

### PR-A — integration tests ya en su lugar (sin cambios)

- `tests/integration/test_tenants_integration.py:382` — `test_cross_tenant_isolation_complete` — ya assert 403 en el user GET (línea 402).
- `tests/integration/test_users_integration.py:280` — `test_admin_a_never_access_tenant_b_resources` — ya assert 403 para GET, PATCH, DELETE.
- `tests/integration/test_users_integration.py:615` — `test_admin_cannot_deactivate_superadmin_via_patch` — ya assert 403.

### PR-A — integration test change required (decisión de usuario sobre RK-6)

- `tests/integration/test_tenants_integration.py:406` — `assert resp.status_code == 404` DEBE cambiarse a `assert resp.status_code == 403`. Esta es la consecuencia user-facing de añadir la tenant Depends. Sin este cambio, el test fallaría porque la Depends ahora devuelve 403 para el caso cross-tenant que el test ejercita. Esta es la decisión explícita del usuario: el test sigue al contrato, el contrato no sigue al test.

### PR-B — unit tests en `tests/unit/test_users_service.py`

- `test_create_user_translates_unique_violation_to_409` — fake un `IntegrityError` con `pgcode='23505'` desde un `db.flush()` mockeado; assert `UserError(409)` se eleva.
- `test_create_user_propagates_non_unique_integrity_error` — fake `pgcode='23503'` (FK violation); assert el `IntegrityError` original se propaga sin traducir.
- `test_create_user_rolls_back_failed_session` — fake el IntegrityError, assert `db.rollback()` fue llamado antes del raise (usar un spy sobre el AsyncSession mock).

### PR-B — integration test en su lugar

- `tests/integration/test_users_integration.py:527` — `test_email_unique_globally_returns_409` — assert 201 después 409. Sin cambio de test necesario; pasa vía el pre-check existente hoy, seguirá pasando tras PR-B.

## 6. Plan de rollout

### Orden de merge (mandatory)

1. **PR-0** (prerequisito) — commit los 3 archivos sin commitear de RLS session-poisoning: `app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`. Conventional commit message: `fix(rls): prevent session poisoning across pooled connections`. Sin cambios de diseño, sin tocar spec. **DEBE mergear primero** porque el patrón de elevación en la nueva Depends depende de las garantías de sesión RLS que estos archivos establecen.
2. **PR-A** — RLS service-layer refactor + tenant pre-check. Toca:
   - `app/dependencies.py` (nueva Depends + factory para users y tenants)
   - `app/modules/users/service.py` (split functions, signature changes)
   - `app/modules/users/router.py` (usa la nueva Depends)
   - `app/modules/tenants/router.py` (usa la nueva tenant Depends; remueve el inline 404 check)
   - `tests/integration/test_tenants_integration.py:406` (assert 404 → 403)
   - `tests/unit/test_dependencies.py` (nuevos unit tests para users y tenants Depends)
   - Conventional commit message: `fix(users,tenants): return 403 on cross-tenant access via service-layer pre-check`
3. **PR-B** — email 409 translation. Toca solo `app/modules/users/service.py:create_user` (añade try/except alrededor de `db.flush()`) y el archivo de unit tests. Conventional commit message: `fix(users): translate unique_violation to 409 on duplicate email`.

PR-A y PR-B pueden revisarse en cualquier orden pero PR-A DEBE aterrizar primero para evitar rebase churn en `service.py`. PR-B no depende del comportamiento runtime de PR-A — solo se beneficia de que PR-A ya haya estabilizado el archivo.

### Database migrations

**Ninguna.** Según la spec y el out-of-scope de la propuesta, este diseño NO DEBE añadir nuevas migraciones alembic. Las policies RLS en `migrations/versions/20260312_2052_initial_schema_712a827b0929.py:94-118` son referencias read-only.

### Feature flag

**No** se añade nuevo feature flag en este diseño. El patrón de elevación es requerido por el contrato 403 — gatearlo detrás de un flag significaría que los 4 tests fallan cuando el flag está off, derrotando el propósito. Rollback es vía git revert (PR-A revert devuelve el contrato 404 en users y revierte el cambio de test en línea 406 si el cambio de test se mergeó atómicamente con la implementación).

Si un incidente futuro hace del patrón de elevación la causa raíz sospechada, el rollback es:
- `git revert <PR-A merge commit>` — restaura el contrato 404 en users (y revierte el cambio de test en línea 406 si el cambio se mergeó atómicamente).
- PR-0 sin mergear se queda — su fix de RLS session poisoning es independientemente seguro.

## 7. Riesgos y mitigaciones

| ID | Riesgo | Mitigation |
|----|--------|------------|
| RK-1 | El cambio de signature de función de servicio rompe callers directos. Grep results: solo `app/modules/users/router.py` y `app/modules/tenants/router.py` importan de `app.modules.users.service`. El router se actualiza en el mismo PR. | PR-A es atómico; los tests corren en cada commit. |
| RK-2 | La ventana de elevación entre `set_config` y `set_tenant_context` expone la sesión a scope superadmin. | El par SET LOCAL se revierte en COMMIT/ROLLBACK; el bloque `try/finally` en la Depends garantiza que el restore corre incluso en excepción. Un comentario de código nombra la garantía de `SET LOCAL`. |
| RK-3 | `e.orig.pgcode` es asyncpg-específico. | Pin asyncpg; añadir un comentario; la función usa `getattr(exc.orig, "pgcode", None) == "23505"` así que un atributo faltante cae a `raise` (sin mis-traducción silenciosa). |
| RK-4 | La nueva Depends introduce un `db.execute` extra por request para elevación incluso en requests same-tenant. | La Depends chequea `current_user.tenant_id == row.tenant_id` y devuelve early; la elevación solo dispara para requests cross-tenant (que son el slow path y el caso raro). Para callers superadmin, no se necesita elevación porque el `set_tenant_context(... , True)` existente de `get_current_user` está en efecto. |
| RK-5 | El factory de Depends crea tres wrappers casi idénticos (`get_user_for_admin_get`, `_patch`, `_delete`). Futuros devs podrían añadir un nuevo HTTP method y olvidarse de añadir un wrapper, dejando el log line con un `method=` incorrecto. | Los tres wrappers viven en `app/dependencies.py` al lado del helper core; el unit test suite cubre cada wrapper. Un docstring en `_user_for_admin` dice "add a new wrapper when adding a new HTTP method to user routes." |
| RK-6 | Tenant cross-access devuelve 403 (consistente con user cross-tenant endpoint). Test `test_tenants_integration.py:406` actualizado. Pre-check para endpoints /tenants añadido en el tenant router. | La Depends reemplaza el viejo check inline 404. El test en línea 406 se actualiza en el mismo PR. El cambio unifica la señal de audit — intentos cross-tenant sobre /users o /tenants aparecen como la misma línea de log `cross_tenant_access_blocked` con la misma respuesta HTTP 403. |
| RK-7 | `update_user` y `deactivate_user` ya no fetchean su propia fila target — la reciben como argumento. Futuros devs podrían llamarlas con un `User` construido a mano y saltarse el pre-check. | Las nuevas signatures hacen `current_user` y `target` parámetros requeridos (sin defaults), y un comentario dice "the router MUST obtain `target` via the new Depends, not via `get_user_internal`." Una regla de linter (manual por ahora) flaguea imports de service desde el router fuera de la nueva Depends. |
| RK-8 | La Depends emite un `db.execute` extra incluso cuando la fila está en el tenant del caller. | El costo es un par `SELECT set_config(...)` (barato) más el mismo SELECT que el viejo `get_user_by_id` habría emitido. Sin regresión medible en el hot path. La tenant Depends NO eleva en 403 cross-tenant — la comparación corre en Python antes de cualquier llamada a DB, ahorrando los dos roundtrips de `set_config` en el path 403. |
| RK-9 | Un caller superadmin leyendo su propio tenant es el nuevo happy path para la tenant Depends — pero los superadmins históricamente bypasean el check inline 404 en el router. La nueva Depends preserva ese path (la branch `is_superadmin` devuelve la fila sin pre-check) así que el flujo superadmin existente queda preservado. | Unit test `test_get_tenant_for_admin_returns_row_for_superadmin` cubre este caso. |

## 8. Out of scope (explícito)

- Trabajo de F2 bajo `openspec/changes/prd-v2-vertical-f2/`.
- Cualquier cambio a las policies RLS en `migrations/versions/20260312_2052_initial_schema_712a827b0929.py:94-118`.
- Los 3 archivos sin commitear de RLS session-poisoning (`app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`) — salen como PR-0 y no se tocan en PR-A o PR-B.
- Nuevas migraciones alembic o cambios de schema.
- UNIQUE parcial por tenant sobre `email` (Opción C de la propuesta queda descartada).
- Enrichment de audit-log más allá de la única línea `cross_tenant_access_blocked` (sin métricas, sin traces, sin audit table separada).
- Replicación multi-region, rate limiting, cambios de jerarquía de roles.
- PATCH y DELETE sobre `/tenants/{id}` — quedan superadmin-only a nivel de router; el pre-check cross-tenant no se extiende a ellos (la superadmin gate es suficiente y ningún test ejercita actualmente una mutación de tenant no-superadmin cross-tenant).

## 9. Open architectural questions

Sin preguntas arquitectónicas abiertas restantes tras la resolución de RK-6. Los 4 OQs de la spec quedan respondidos en el record de decisiones (`sdd/fix-f1-remaining-rls-403-and-email-409/decisions`):
- OQ-1 resuelto: los campos del log son `caller_id`, `target_id`, `method`, `endpoint`. Sin `tenant_id`.
- OQ-2 resuelto: la elevación vive en una NUEVA FastAPI Depends; la capa de servicio queda limpia.
- OQ-3 resuelto: `get_user_by_id` se parte en `get_user_for_admin` (pre-check) y `get_user_internal` (system path, sin pre-check).
- OQ-4 resuelto: los 3 archivos sin commitear salen como PR-0; orden de merge PR-0 → PR-A → PR-B.

RK-6 también queda resuelto: tenant cross-access ahora devuelve 403, consistente con el user cross-tenant endpoint. La asimetría 404-on-tenant-cross-access se elimina con esta revisión.

## 10. Resumen del test plan para PR-B

| Requirement | Test file (new) | Test file (existing) | Line |
|-------------|-----------------|----------------------|------|
| R07 | `tests/unit/test_users_service.py::test_create_user_translates_unique_violation_to_409` | `tests/integration/test_users_integration.py` | 527 |
| R08 | `tests/unit/test_users_service.py::test_create_user_propagates_non_unique_integrity_error` | — | — |
| R09 | `tests/unit/test_users_service.py::test_create_user_rolls_back_failed_session` | — | — |
