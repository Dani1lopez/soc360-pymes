# Spec: fix-f1-remaining-rls-403-and-email-409

## 1. Propósito

Cerrar los últimos 4 tests de integración fallando en `fix/heal-f1` forzando dos cambios de contrato: (a) acceso cross-tenant sobre recursos de usuario DEBE devolver HTTP 403 (no 404) para que el evento sea distinguible en audit y access logs, y (b) email duplicado en creación de usuario DEBE devolver HTTP 409 incluso bajo insert concurrente. La spec introduce un pre-check de tenant en capa de servicio con elevación scoped de sesión superadmin para el contrato 403, y un traductor de `IntegrityError` en `create_user` para el contrato 409.

## 2. Alcance

**In scope**
- Refactor de capa de servicio en `app/modules/users/service.py` para que las funciones que apuntan a usuario reciban `current_user` y comparen `tenant_id` en Python antes de cualquier DB read o write.
- Elevación de la DB session del request-handler a contexto superadmin por la duración del pre-check SELECT, usando `set_config(..., true)` para que la elevación sea transaction-local y no pueda leakear cross requests en la connection pool.
- Un wrapper `try/except IntegrityError` alrededor de `db.flush()` en `service.create_user` que traduzca `pgcode='23505'` a `UserError(status_code=409)` y haga rollback de la unidad de trabajo fallida.
- Los 3 casos de test RLS en `tests/integration/test_tenants_integration.py:382`, `tests/integration/test_users_integration.py:280`, y `tests/integration/test_users_integration.py:615` DEBEN pasar con `status_code == 403`.
- El test de email en `tests/integration/test_users_integration.py:527` DEBE pasar con `status_code == 409`.
- Tests unitarios para las nuevas branches (pre-check de tenant 403, traductor IntegrityError → 409, rollback no envenena sesión).

**Out of scope**
- Cualquier modificación a las policies RLS en `migrations/versions/20260312_2052_initial_schema_712a827b0929.py:94-118` (las definiciones de `rls_tenants`, `rls_users`, `rls_refresh_tokens` son referencias read-only para este cambio).
- Cualquier modificación a los 3 archivos sin commitear en `fix/heal-f1` que ya implementan el fix de RLS session poisoning: `app/core/database.py`, `app/dependencies.py`, y `tests/integration/test_auth_login_event_flow.py`. Esos aterrizan en su propio commit.
- Cualquier trabajo de F2 bajo `openspec/changes/prd-v2-vertical-f2/`.
- Sin nuevas migraciones alembic. Sin cambios de schema.
- Sin cambio a la regla de producto de que `email` es globalmente único. Índices UNIQUE parciales por tenant están descartados.
- Sin refactor de `_is_email_taken` más allá del mínimo necesario.
- Sin reescritura del users router más allá del mínimo para pasar `current_user` al servicio.

## 3. Non-Goals

- Sin enrichment de audit log de accesos cross-tenant (el sistema aún no los loguea como clase de evento distinta — out of scope).
- Sin replicación multi-region, sin nuevas métricas, sin tracing.
- Sin cambio a la policy `rls_tenants` (que devuelve 404 para reads de tenant cross-tenant — `tests/integration/test_tenants_integration.py:406`).
- Sin cambio a la policy `rls_refresh_tokens`.
- Sin rate limiting o throttling en creación de usuarios.
- Sin cambio a la jerarquía de roles (`viewer` < `admin` < `superadmin`).

## 4. Frontera de PRs

El cambio sale como exactamente 3 PRs contra `fix/heal-f1`:

| PR | Título | Alcance | Test files afectados |
|----|--------|---------|---------------------|
| **PR-0** | RLS session poisoning (prerequisito) | Commit de los 3 archivos sin commitear. Sin cambios de diseño. | `tests/integration/test_auth_login_event_flow.py` |
| **PR-A** | RLS: acceso cross-tenant a usuario devuelve 403 (pre-check en capa de servicio) | Refactor de capa de servicio: `get_user_by_id`, `update_user`, `deactivate_user` aceptan `current_user` y comparan `tenant_id`. Patrón de elevación en request-handler. | `tests/integration/test_tenants_integration.py:382`, `tests/integration/test_users_integration.py:280`, `tests/integration/test_users_integration.py:615`, `tests/integration/test_tenants_integration.py:406` |
| **PR-B** | Unicidad de email: email duplicado devuelve 409 en race | `try/except IntegrityError` en `service.create_user` traducido a `UserError(409)`. | `tests/integration/test_users_integration.py:527` |

Orden mandatorio: PR-0 → PR-A → PR-B. PR-0 es prerequisito duro (PR-A depende de las garantías de sesión RLS que PR-0 establece). PR-B puede aterrizar en cualquier orden relativo a PR-A, pero DEBE aterrizar después de PR-A para que el archivo `service.py` esté estabilizado.

## 5. Requisitos

### R01 — Cross-tenant user GET devuelve 403

**Statement.** El sistema DEBE devolver HTTP 403 cuando un usuario no-superadmin solicita `GET /api/v1/users/{user_id}` y el `tenant_id` del usuario target difiere del `tenant_id` del caller.

**Rationale.** Workflows de audit y compliance requieren que acceso cross-tenant aparezca como un evento distinto y distinguible en respuestas HTTP y access logs.

**Acceptance criteria.**
- El pre-check ocurre en la capa de servicio antes de cualquier query state-mutating o antes de devolver una respuesta "row not found".
- El body de la respuesta 403 es JSON con `detail` indicando permisos insuficientes.
- Un caller superadmin PUEDE leer cualquier usuario cross tenants y NO DEBE recibir 403 de este pre-check.

**Scenarios.**

- **S01.1 — Admin A lee el perfil de Admin B (caso GET del test #2).**
  - GIVEN admin A autenticado en tenant A y admin B existe en tenant B con `id=ADMIN_B_ID`
  - WHEN admin A llama `GET /api/v1/users/{ADMIN_B_ID}` con `admin_a_headers`
  - THEN el status de respuesta es 403
  - AND el `detail` del body de respuesta es un string no vacío

- **S01.2 — Admin lee su propio usuario (sin falso positivo).**
  - GIVEN admin A autenticado
  - WHEN admin A llama `GET /api/v1/users/{ADMIN_A_ID}` (su propio id) con `admin_a_headers`
  - THEN el status de respuesta es 200
  - AND el body de respuesta contiene el registro de admin A

- **S01.3 — Superadmin lee usuario de cualquier tenant.**
  - GIVEN un superadmin autenticado
  - WHEN el superadmin llama `GET /api/v1/users/{ADMIN_B_ID}`
  - THEN el status de respuesta es 200
  - AND el body de respuesta contiene el registro de admin B

### R02 — Cross-tenant user PATCH devuelve 403

**Statement.** El sistema DEBE devolver HTTP 403 cuando un usuario no-superadmin solicita `PATCH /api/v1/users/{user_id}` y el `tenant_id` del usuario target difiere del `tenant_id` del caller. Ningún campo de fila se modifica.

**Rationale.** Simétrico con R01 para operaciones de write. Un pre-check que permita al read leakear (ej. vía el pre-check SELECT) y solo bloquee la mutación no es aceptable.

**Acceptance criteria.**
- El pre-check ocurre antes de `db.flush()` sobre el registro de usuario.
- El pre-check eleva 403 y cortocircuita el resto del flow de update.
- La DB no se muta (sin estado parcial).

**Scenarios.**

- **S02.1 — Admin A parchea Admin B (caso PATCH del test #2).**
  - GIVEN admin A autenticado en tenant A y admin B existe en tenant B
  - WHEN admin A llama `PATCH /api/v1/users/{ADMIN_B_ID}` con `{"full_name": "Hacked"}` y `admin_a_headers`
  - THEN el status de respuesta es 403
  - AND el `full_name` de admin B en la DB queda sin cambios (verificado por un read exitoso posterior)

- **S02.2 — Superadmin PATCH is_active=False sobre sí mismo devuelve 409 (comportamiento existente, no regresionado).**
  - GIVEN un superadmin autenticado
  - WHEN el superadmin llama `PATCH /api/v1/users/{SUPERADMIN_ID}` con `{"is_active": false}`
  - THEN el status de respuesta es 409 (protección de self-deactivation)
  - AND el `is_active` del superadmin queda sin cambios

- **S02.3 — Admin PATCH is_active=False sobre superadmin devuelve 403 (test #4).**
  - GIVEN admin A autenticado y un superadmin existe con `id=SUPERADMIN_ID`
  - WHEN admin A llama `PATCH /api/v1/users/{SUPERADMIN_ID}` con `{"is_active": false}` y `admin_a_headers`
  - THEN el status de respuesta es 403
  - AND el `is_active` del superadmin en la DB queda sin cambios

### R03 — Cross-tenant user DELETE devuelve 403

**Statement.** El sistema DEBE devolver HTTP 403 cuando un usuario no-superadmin solicita `DELETE /api/v1/users/{user_id}` y el `tenant_id` del usuario target difiere del `tenant_id` del caller.

**Rationale.** Simétrico con R01 y R02. Deactivación cross-tenant debe bloquearse lo más temprano posible, antes de cualquier token revocation o flip de `is_active`.

**Acceptance criteria.**
- El pre-check ocurre antes de que `is_active` se setee a `False` y antes de cualquier token revocation.

**Scenarios.**

- **S03.1 — Admin A deletea Admin B (caso DELETE del test #2).**
  - GIVEN admin A autenticado en tenant A y admin B existe en tenant B
  - WHEN admin A llama `DELETE /api/v1/users/{ADMIN_B_ID}` con `admin_a_headers`
  - THEN el status de respuesta es 403
  - AND el `is_active` de admin B en la DB queda sin cambios

- **S03.2 — Admin deletea superadmin devuelve 403.**
  - GIVEN admin A autenticado y un superadmin existe
  - WHEN admin A llama `DELETE /api/v1/users/{SUPERADMIN_ID}` con `admin_a_headers`
  - THEN el status de respuesta es 403
  - AND el `is_active` del superadmin en la DB queda sin cambios

### R04 — Funciones de capa de servicio reciben `current_user` y comparan `tenant_id`

**Statement.** Las funciones de servicio `get_user_by_id`, `update_user` y `deactivate_user` DEBEN aceptar un parámetro `current_user: User` y comparar su `tenant_id` con el `tenant_id` del usuario target antes de devolver data o mutar estado. En mismatch, la función DEBE elevar una excepción mapeada a 403.

**Rationale.** Centralizar el check en la capa de servicio es el lugar convencional donde futuros engineers buscarán reglas de autorización. Devolver 403 desde un único chokepoint es auditable y testeable.

**Acceptance criteria.**
- El parámetro `current_user` es posicional o keyword y es requerido (sin default).
- La comparación de `tenant_id` ocurre ANTES de cualquier `db.flush()` y ANTES de que la función devuelva la fila al router.
- Un `current_user` superadmin se salta la comparación.
- El 403 se mapea a través de la traducción existente `UserError` → `HTTPException` en el router.

### R05 — Elevación de superadmin en request-handler está scoped al pre-check

**Statement.** Cuando el request handler necesita leer una fila de usuario que RLS ocultaría del contexto de tenant del caller (para que el servicio pueda correr el tenant pre-check), el handler DEBE elevar la DB session del request a contexto superadmin solo para el pre-check SELECT, y DEBE restaurar el contexto de tenant del caller para la mutación o read posterior.

**Rationale.** Sin elevación, RLS oculta la fila cross-tenant, `get_user_by_id` devuelve `None`, y el pre-check es inalcanzable. Con elevación no controlada, la superficie de bypass se expande y el pool bleed de conexión es posible.

**Acceptance criteria.**
- La elevación usa `SELECT set_config('app.is_superadmin', 'true', true)` — el tercer argumento `true` hace el setting transaction-local (`SET LOCAL`), así que se limpia automáticamente en COMMIT/ROLLBACK y no puede leakear al siguiente request que reuse la conexión pooled.
- La elevación también llama `SELECT set_config('app.current_tenant', '', true)` para neutralizar cualquier tenant scope previo.
- El bloque de elevación contiene exactamente el SELECT que lee la fila target.
- Tras el pre-check, el handler DEBE llamar `set_tenant_context(db, current_user.tenant_id, current_user.is_superadmin)` para restaurar el contexto de request canónico antes de invocar la mutación de servicio.
- El mismo patrón `SET LOCAL` usado en el `app/dependencies.py:90-93` sin commitear (dentro de `get_current_user`) es el modelo.

### R06 — Flujos same-tenant normales quedan bajo contexto de tenant

**Statement.** Un request usuario-a-usuario-en-mismo-tenant (ej. admin A PATCHea viewer A, o cualquier read same-tenant) DEBE ejecutarse enteramente bajo el contexto de tenant del caller sin elevación de superadmin. RLS sigue protegiendo el path.

**Rationale.** El pre-check solo es necesario cuando la fila target NO es visible bajo el tenant del caller. Para operaciones same-tenant, RLS es la única fuente de verdad y la elevación es innecesaria e insegura.

**Acceptance criteria.**
- Un handler que detecte `target.tenant_id == current_user.tenant_id` NO DEBE llamar `set_config('app.is_superadmin', 'true', ...)`.
- Tests same-tenant (ej. `test_admin_can_update_user_in_same_tenant`) siguen pasando sin nuevos `set_config` en sus paths.

### R07 — Email duplicado en `POST /api/v1/users/` devuelve 409

**Statement.** Cuando `POST /api/v1/users/` se llama con un `email` que ya existe en la tabla `users` (en cualquier tenant), el sistema DEBE devolver HTTP 409, incluso bajo la condición de carrera donde el duplicado se crea entre el pre-check y el INSERT.

**Rationale.** El pre-check actual `_is_email_taken` tiene una ventana TOCTOU: dos requests concurrentes con el mismo email ambos pasan el pre-check, la `users_email_key` UNIQUE constraint de la DB dispara, y la aplicación devuelve HTTP 500. Unicidad global de email es una regla de producto dura, y el contrato es 409.

**Acceptance criteria.**
- El 409 se devuelve tanto en el path de pre-check (comportamiento actual) como en el path post-flush (comportamiento nuevo).
- El 409 post-flush es el resultado de un `IntegrityError` traducido.
- El mensaje de error está en español para coincidir con el resto de los mensajes 4xx user-facing del módulo: `"El email ya está registrado"`.

**Scenarios.**

- **S07.1 — Email duplicado secuencial (primera mitad del test #3).**
  - GIVEN admin A autenticado
  - WHEN admin A llama `POST /api/v1/users/` con `email=duplicate@test.test` y `tenant_id=TENANT_A_ID`
  - THEN el status de respuesta es 201
  - AND cuando admin A llama `POST /api/v1/users/` de nuevo con el mismo `email` (cualquier `tenant_id`)
  - THEN el status de respuesta es 409
  - AND el `detail` del body de respuesta contiene la frase "ya está registrado"

- **S07.2 — Email duplicado cross-tenant.**
  - GIVEN un usuario con `email=duplicate@test.test` ya existe en tenant A
  - WHEN admin B llama `POST /api/v1/users/` con `email=duplicate@test.test` y `tenant_id=TENANT_B_ID`
  - THEN el status de respuesta es 409

### R08 — `IntegrityError` se traduce solo en `pgcode == '23505'`

**Statement.** `service.create_user` DEBE capturar `sqlalchemy.exc.IntegrityError` después de `db.flush()` e inspeccionar `e.orig.pgcode`. La traducción a `UserError(status_code=409)` DEBE ocurrir solo cuando `pgcode == '23505'` (PostgreSQL `unique_violation`). Todas las demás variantes de `IntegrityError` (violaciones FK `23503`, violaciones check `23514`, etc.) DEBEN propagarse sin traducir.

**Rationale.** Capturar `IntegrityError` ampliamente y traducir a 409 enmascararía violaciones FK y check que indican bugs genuinos de data integrity. El filtro `pgcode` es el atributo documentado de asyncpg/SQLAlchemy que identifica unique_violation.

**Acceptance criteria.**
- La cláusula `except` chequea `e.orig.pgcode == '23505'` exactamente.
- Otras variantes de `IntegrityError` re-elevan la excepción original (o la envuelven en un `UserError` no-409 si la fase de diseño lo decide — pero NO 409).
- Un comentario de código nombra el supuesto asyncpg-específico sobre `e.orig.pgcode`.

**Scenarios.**

- **S08.1 — IntegrityError no-23505 se propaga.**
  - GIVEN se puede construir un escenario de violación de FK (ej. POST con un `tenant_id` que referencia un tenant inexistente — aunque el pre-check `_get_active_tenant` hace difícil llegar, el test debe usar un fixture a nivel unitario que inyecte un `IntegrityError` falso con `pgcode='23503'`)
  - WHEN `service.create_user` se llama bajo ese fixture
  - THEN el `IntegrityError` original se propaga fuera de la función
  - AND el status de respuesta es 500 (o lo que sea que el global handler mapee `IntegrityError` a), NO 409

### R09 — Sesión se hace rollback tras `IntegrityError` traducido

**Statement.** Cuando `service.create_user` captura el `IntegrityError` `unique_violation`, la función DEBE `await db.rollback()` antes de elevar el `UserError(409)` traducido.

**Rationale.** Tras un `flush()` fallido la sesión de SQLAlchemy queda en estado fallido: la siguiente operación en el mismo request (ej. un `db.execute` de seguimiento en el router o un global handler) elevará `PendingRollbackError`. Rollback explícito limpia el estado fallido.

**Acceptance criteria.**
- `await db.rollback()` se llama entre el `except` y el raise.
- Un test de regresión ejercita dos user creations en el mismo request: la primera es un duplicado (eleva 409), la segunda es un no-duplicado (debe tener éxito). Si rollback falta, la segunda llamada eleva `PendingRollbackError`.

**Scenarios.**

- **S09.1 — Duplicado y no-duplicado en el mismo request.**
  - GIVEN un usuario con `email=first@test.test` ya existe
  - WHEN un test client hace dos llamadas `POST /api/v1/users/` en el mismo request/session: primero con `email=first@test.test` (espera 409), después con `email=second@test.test` (espera 201)
  - THEN la segunda llamada devuelve 201
  - AND el usuario con `email=second@test.test` queda persistido

### R10 — Sin regresión en tests existentes que pasan

**Statement.** Todos los tests de integración que pasan en el working tree actual de `fix/heal-f1` (excluyendo los 4 fallos objetivo) DEBEN seguir pasando tras aterrizar PR-A y PR-B.

**Rationale.** El refactor de las signatures de funciones de capa de servicio y el patrón de elevación es el cambio de mayor riesgo en esta spec. La suite completa de integración es la red de regresión.

**Acceptance criteria.**
- El run completo de `pytest tests/integration/` en `fix/heal-f1` está verde tras aterrizar PR-A.
- El run completo de `pytest tests/integration/` está verde tras aterrizar PR-B.
- Ruff y mypy (si está configurado) no reportan nuevas violaciones.

## 6. Cross-Cutting Requirements

**Seguridad.**
- La elevación de superadmin usa `set_config(..., true)` (tercer argumento), que produce un `SET LOCAL` que se limpia automáticamente al final de la transacción. Esto es no-negociable: un `set_config(..., false)` leakearía cross requests en la conexión pooled.
- El bloque de elevación en el handler DEBE ser lo más angosto posible (un único SELECT) y DEBE ir seguido de una llamada a `set_tenant_context(...)` que re-establezca el contexto de tenant del caller.
- Ninguna función de servicio almacena la sesión elevada en una variable a nivel de módulo. La `db: AsyncSession` es la dependencia scoped al request y no se comparte.

**Observabilidad.**
- Las llamadas existentes `logger.info("user_created", ...)` y `logger.info("user_updated", ...)` siguen disparando en éxito.
- Una línea de log `logger.warning("cross_tenant_access_blocked", caller_id=..., target_id=..., endpoint=...)` se emite en el sitio del raise 403. Esta es la única línea de log nueva requerida por la spec; es la señal que los auditores buscarán.
- Sin nuevas métricas ni traces.

**Forma de respuesta de error.**
- Todas las respuestas 4xx son JSON de la forma `{"detail": "<message>"}` (default de FastAPI), que coincide con las respuestas existentes de este módulo.
- Mensajes 403 para acceso cross-tenant están en español: `"Permisos insuficientes"` (coincide con el mensaje existente en `app/modules/users/router.py:117` y `:160`).
- 409 para email duplicado está en español: `"El email ya está registrado"` (coincide con el mensaje existente en `app/modules/users/service.py:52`).

**Cobertura de tests.**
- Tests unitarios para las nuevas branches: (a) tenant pre-check devuelve 403 en mismatch, (b) tenant pre-check se bypasea para superadmin, (c) `IntegrityError` con `pgcode='23505'` se traduce a 409, (d) `IntegrityError` con otro `pgcode` se propaga, (e) rollback limpia la sesión fallida.
- Los 4 tests de integración objetivo siguen siendo la prueba end-to-end.
- Ruff y mypy DEBEN pasar. El cambio de signature de función en R04 es un breaking API change para callers directos de las funciones de servicio — la fase de diseño DEBE auditarlos y actualizarlos.

## 7. Open Questions

- **OQ-1.** ¿Debería la línea de log del 403 cross-tenant incluir el `endpoint` y HTTP method? La spec requiere al menos `caller_id` y `target_id`, pero la fase de diseño puede querer el method para distinguir reads intentados de writes intentados para ponderación de audit.
- **OQ-2.** Para el patrón de elevación: ¿debería el handler restaurar el contexto de tenant ANTES de llamar al pre-check del servicio (así el servicio corre el SELECT bajo el tenant del caller y el SELECT devuelve naturalmente None para filas cross-tenant), o DESPUÉS de llamar al pre-check del servicio (así el SELECT del servicio corre bajo superadmin y lee explícitamente la fila cross-tenant)? La spec dice que R05 eleva ANTES del pre-check SELECT; la fase de diseño puede querer invertir esto y tener el pre-check SELECT ocurriendo bajo el tenant del caller y devolviendo None (que entonces se mapearía a 404, no 403 — contradiciendo R01). La fase de diseño DEBE resolver esto; la spec requiere el outcome 403.
- **OQ-3.** ¿Debería `get_user_by_id` partirse en dos funciones — una que devuelva `None` para "fila no visible bajo RLS" (usada por el path de self-read del router) y otra que devuelva la fila solo tras un tenant-match check (usada por el path de pre-check cross-tenant)? ¿O debería una única función tomar un argumento `current_user` y el caller decide qué comportamiento quiere vía un flag? La spec no exige una shape sobre la otra.
- **OQ-4.** Los 3 archivos sin commitear de RLS session poisoning (`app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`) — ¿se commitean como un PR prerequisito separado antes de PR-A, o como parte de PR-A? La spec dice que están out of scope y no deben modificarse, pero el orden de deployment es una pregunta de proceso, no técnica.

## 8. Riesgos

| ID | Riesgo | Likelihood | Impact | Mitigation |
|----|--------|------------|--------|------------|
| RK-1 | El cambio de signature de función en R04 rompe callers directos de las funciones de servicio (cualquier otro módulo que importe `service.get_user_by_id`, `service.update_user` o `service.deactivate_user`). | Media | Media | La fase de diseño DEBE grepear por callers y actualizarlos. El refactor es un cambio de signature duro, no una adición backward-compatible. |
| RK-2 | El patrón de elevación en R05 deja una ventana entre `set_config('app.is_superadmin', 'true')` y el `set_tenant_context` posterior donde la sesión es superadmin. Si una excepción se eleva dentro del bloque de elevación, el rollback limpia el `SET LOCAL`, así que no hay leak — pero un lector de código que vea el patrón podría copiarlo sin la garantía de rollback. | Baja | Alta | La fase de diseño DEBE añadir un comentario de código nombrando la garantía de `SET LOCAL` y la dependencia de rollback. El patrón ya se usa en `app/dependencies.py:90-93`, así que el precedente está en el mismo archivo. |
| RK-3 | `e.orig.pgcode` es asyncpg-específico. Si SQLAlchemy algún día cambia el async driver a uno que no popule `pgcode` (ej. psycopg3 async), la traducción de `IntegrityError` silenciosamente deja de funcionar y devuelve 500. | Baja | Media | Pin asyncpg en el manifiesto de dependencias. Añadir un comentario de código nombrando el supuesto. Opcionalmente, fallback a matchear por string el nombre de la constraint en el mensaje de error. |
| RK-4 | El test de email duplicado en `test_users_integration.py:527` puede haberse escrito asumiendo 404 (no 409) en el duplicado cross-tenant — la spec asume 409 basándose en el nombre del test y el record de decisión. Si el body del test realmente afirma 404 en algún lugar, la fase de diseño DEBE actualizarlo. | Baja | Baja | La fase de diseño lee el test completo antes de diseñar la traducción de excepción. |
| RK-5 | PR-A y PR-B ambos tocan `app/modules/users/service.py`. Si PR-B aterriza primero o se rebasa sobre el estado sin mergear de PR-A, el diff queda sucio. | Baja | Baja | La sección de frontera de PRs exige PR-A primero, PR-B segundo. |
| RK-6 | La aserción de `test_tenants_integration.py:406` (`assert resp.status_code == 404` para `GET /tenants/{id}` cross-tenant) está IN SCOPE para PR-A y DEBE pasar a 403. La decisión de diseño es unificar el contrato 403 cross-tenant. | Baja | Media | La sección de Alcance de la spec nombra explícitamente este test. La descripción del PR debe llamarlo out. |

## 9. Resumen del Test Plan

| Requirement | Test file (new) | Test file (existing) | Line |
|-------------|-----------------|----------------------|------|
| R01 | `tests/unit/test_users_service.py::test_get_user_by_id_raises_403_on_tenant_mismatch` | `tests/integration/test_tenants_integration.py` | 382 |
| R01 | `tests/unit/test_users_service.py::test_get_user_by_id_returns_user_for_superadmin` | `tests/integration/test_users_integration.py` | 280 |
| R02 | `tests/unit/test_users_service.py::test_update_user_raises_403_on_tenant_mismatch_no_flush` | `tests/integration/test_users_integration.py` | 280 |
| R02 | `tests/unit/test_users_service.py::test_update_user_raises_403_when_admin_patches_superadmin` | `tests/integration/test_users_integration.py` | 615 |
| R03 | `tests/unit/test_users_service.py::test_deactivate_user_raises_403_on_tenant_mismatch` | `tests/integration/test_users_integration.py` | 280 |
| R04 | `tests/unit/test_users_service.py::test_service_functions_require_current_user_arg` | — | — |
| R05 | `tests/unit/test_users_service.py::test_handler_restores_tenant_context_after_pre_check` (o test de integración sobre el router) | — | — |
| R06 | `tests/integration/test_users_integration.py` (tests same-tenant existentes no deben regresar) | `tests/integration/test_users_integration.py` | varios |
| R07 | `tests/unit/test_users_service.py::test_create_user_translates_unique_violation_to_409` | `tests/integration/test_users_integration.py` | 527 |
| R08 | `tests/unit/test_users_service.py::test_create_user_propagates_non_unique_integrity_error` | — | — |
| R09 | `tests/unit/test_users_service.py::test_create_user_rolls_back_failed_session` | — | — |
| R10 | — | full `pytest tests/integration/` | — |

## 10. Plan de Rollback

**PR-0 rollback.** Revertir el commit. Los tests vuelven a su estado pre-fix (los 3 RLS session poisoning tests vuelven a fallar; los 4 objetivo siguen fallando).

**PR-A rollback.** Revertir el PR. Los 3 tests objetivo vuelven a fallar; `fix/heal-f1` vuelve al estado pre-PR-A. Los 3 archivos sin commitear de RLS session poisoning se quedan en la rama.

**PR-B rollback.** Revertir el PR. El test de email duplicado en `tests/integration/test_users_integration.py:527` vuelve a fallar bajo la condición de carrera; el caso secuencial (capturado por el pre-check) sigue funcionando.

**Rollback de entorno tipo producción.** Los 3 PRs son código de aplicación puro; no hay migraciones involucradas. Un revert-and-redeploy es suficiente. No se necesita rollback a nivel DB.

**Orden de operaciones.** Si los 3 PRs están desplegados y PR-A debe rollbackearse, rollback PR-A primero mientras PR-0 y PR-B se quedan. El contrato 409 es independiente del contrato 403. El orden inverso (rollback PR-B primero) también es seguro.
