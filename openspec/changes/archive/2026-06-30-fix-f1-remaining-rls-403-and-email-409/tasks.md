# Tasks: fix-f1-remaining-rls-403-and-email-409

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines (total) | ~180–220 (PR-0: ~10, PR-A: ~120–150, PR-B: ~50–60) |
| 400-line budget risk | Low (per PR and total) |
| Chained PRs recommended | Yes — PR-0 → PR-A → PR-B (dependencia dura: PR-A depende de las garantías de sesión que PR-0 establece) |
| Suggested split | PR-0 (prerequisito) + PR-A (RLS 403) + PR-B (email 409) — ya decidido |
| Delivery strategy | ask-on-risk (default) — el usuario debe confirmar el plan chained de 3 PRs antes de sdd-apply |
| Chain strategy | stacked-to-main — cada PR mergea a main en orden; PR-0 es tiny, PR-A y PR-B son independientemente revertibles |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: stacked-to-main
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Base branch | Notes |
|------|------|-----------|-------------|-------|
| 1 | Commit uncommitted RLS session-poisoning files | PR-0 | `fix/heal-f1` | Sin cambio de diseño, prerequisito para PR-A |
| 2 | Service-layer pre-check devuelve 403 en cross-tenant user/tenant access | PR-A | `fix/heal-f1` (after PR-0) | Nueva Depends, service split, router updates, test fix at line 406 |
| 3 | Email duplicado devuelve 409 vía IntegrityError translator | PR-B | `fix/heal-f1` (after PR-A) | try/except en `create_user` + unit tests; toca el mismo `service.py` así que aterriza después de que PR-A lo estabilice |

---

## Phase 1: PR-0 — Commit RLS session-poisoning prerequisite

**Goal:** Aterrizar los 3 archivos sin commitear de RLS session-poisoning como un único conventional commit. Sin cambios de diseño, sin cambios de spec. Baja los fallos de tests de integración de 7 a 4 (los 3 RLS session-poisoning tests empiezan a pasar).

- [x] **T-PR0.01** Commit los 3 archivos sin commitear con conventional commit
  - `fix(rls): prevent session poisoning across pooled connections`
  - Files: `app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`
  - Verificar `git diff --staged` muestra ~7 inserted / 2 deleted lines en total
  - Acceptance: Single commit en `fix/heal-f1`; sin cambios de diseño; diff matchea el handoff acordado
  - Test: `git log -1 --stat` muestra exactamente los 3 archivos

- [x] **T-PR0.02** Run integration suite y confirmar 4 fallos restantes
  - `uv run pytest tests/integration/ -v 2>&1 | tail -50`
  - Acceptance: Test count baja de 7 fallos a 4 (los 3 RLS session-poisoning tests ahora pasan; los 4 RLS-403/email-409 tests siguen fallando)
  - Test: `uv run pytest tests/integration/test_auth_login_event_flow.py -v` → todo verde

- [x] **T-PR0.VERIFY** PR-0 verification
  - Run full integration suite
  - Test: `uv run pytest tests/integration/ -v`
  - Acceptance: 4 fallos conocidos quedan (no 7); sin nuevos fallos introducidos

---

## Phase 2: PR-A — RLS service-layer pre-check (cross-tenant 403)

**Goal:** Acceso cross-tenant sobre endpoints de user y tenant devuelve 403 vía una nueva FastAPI Depends que eleva, chequea y restaura. Capa de servicio queda auth-clean. `test_tenants_integration.py:406` actualizado para esperar 403 (contrato unificado según RK-6).

### 2.1 Foundation: nueva Depends en `app/dependencies.py`

- [x] **T-PRA.01** Añadir `_log_cross_tenant_attempt` helper a `app/dependencies.py`
  - Single chokepoint para la línea de log del 403 (decisión OQ-1)
  - Fields: `caller_id`, `target_id`, `method`, `endpoint`; NO `tenant_id` (avoidance de info sensible)
  - Files: `app/dependencies.py`
  - Acceptance: Helper definido; `logger.warning("cross_tenant_access_blocked", ...)` call con exactamente 4 fields
  - Test: unit test en `tests/unit/test_dependencies.py::test_log_cross_tenant_attempt_includes_required_fields`
  - Dependencies: none
  - Size: S
  - Spec: R01, R03 (observability cross-cutting)

- [x] **T-PRA.02** Añadir `_get_user_for_admin` core helper a `app/dependencies.py`
  - Eleva vía `set_config('app.is_superadmin', 'true', true)` + `set_config('app.current_tenant', '', true)` (par SET LOCAL)
  - SELECTea la fila target, compara `row.tenant_id` con `current_user.tenant_id`, restaura contexto vía `set_tenant_context`
  - Superadmin path: sin elevación, devuelve fila o 404
  - Files: `app/dependencies.py`
  - Acceptance: Helper definido con signature `(user_id, current_user, db, method, endpoint) -> User`; eleva 403 en mismatch, 404 en missing row
  - Test: unit test en `tests/unit/test_dependencies.py::test_get_user_for_admin_*` (4 cases: same-tenant, cross-tenant, superadmin, missing)
  - Dependencies: T-PRA.01
  - Size: M
  - Spec: R01, R02, R03, R04, R05

- [x] **T-PRA.03** Añadir factory + wrappers `get_user_for_admin_get/patch/delete` a `app/dependencies.py`
  - `_user_for_admin(method)` factory devuelve una Depends de una línea que llama al core helper con el label de method correcto
  - Tres wrappers: `get_user_for_admin_get`, `get_user_for_admin_patch`, `get_user_for_admin_delete`
  - Files: `app/dependencies.py`
  - Acceptance: Tres Depends públicas exportadas; docstring en factory dice "add a new wrapper when adding a new HTTP method"
  - Test: unit test en `tests/unit/test_dependencies.py::test_user_for_admin_wrappers_exist`
  - Dependencies: T-PRA.02
  - Size: S
  - Spec: R04, R05

- [x] **T-PRA.04** Añadir `get_tenant_for_admin` core helper + `get_tenant_for_admin_get` wrapper a `app/dependencies.py`
  - Compara URL `tenant_id` con `current_user.tenant_id` ANTES de cualquier SELECT (inversión de la user Depends)
  - No se necesita elevación para 403 cross-tenant (pre-check corre en Python)
  - Superadmin path: sin pre-check, devuelve fila o 404
  - Files: `app/dependencies.py`
  - Acceptance: Helper definido; eleva 403 en mismatch, 404 en missing row cuando same-tenant
  - Test: unit test en `tests/unit/test_dependencies.py::test_get_tenant_for_admin_*` (3 cases: same-tenant, cross-tenant, superadmin)
  - Dependencies: T-PRA.01
  - Size: M
  - Spec: R01 (tenants), RK-6 (contrato unificado)

### 2.2 Capa de servicio: `app/modules/users/service.py`

- [x] **T-PRA.05** Partir `get_user_by_id` en `get_user_for_admin` + `get_user_internal`
  - `get_user_for_admin(current_user, target_id, db)` — pre-checked read, eleva UserError(404) si la fila desapareció (TOCTOU)
  - `get_user_internal(target_id, db)` — system/superadmin path, sin pre-check, devuelve User | None
  - Files: `app/modules/users/service.py`
  - Acceptance: Dos funciones definidas; viejo `get_user_by_id` removido; callers actualizados
  - Test: unit tests en `tests/unit/test_users_service.py::test_get_user_for_admin_*` y `test_get_user_internal_*`
  - Dependencies: none
  - Size: M
  - Spec: R04 (decisión OQ-3)

- [x] **T-PRA.06** Reescribir `update_user` para aceptar target pre-checked
  - Nueva signature: `update_user(current_user, target, data, db, redis)` — target es una fila User pre-checked desde la Depends
  - Remover la llamada interna a `get_user_by_id` (la Depends ya fetcheó y autorizó la fila)
  - Files: `app/modules/users/service.py`
  - Acceptance: Función acepta parámetro `target`; sin DB fetch interno; field-application logic sin cambios
  - Test: unit test en `tests/unit/test_users_service.py::test_update_user_does_not_fetch_target`
  - Dependencies: T-PRA.05
  - Size: S
  - Spec: R02, R04, RK-7 (contrato de signature)

- [x] **T-PRA.07** Reescribir `deactivate_user` para aceptar target pre-checked
  - Nueva signature: `deactivate_user(current_user, target, db, redis)` — target está pre-checked
  - Files: `app/modules/users/service.py`
  - Acceptance: Función acepta parámetro `target`; sin DB fetch interno
  - Test: unit test en `tests/unit/test_users_service.py::test_deactivate_user_does_not_fetch_target`
  - Dependencies: T-PRA.05
  - Size: S
  - Spec: R03, R04, RK-7

### 2.3 Router wiring: `app/modules/users/router.py`

- [x] **T-PRA.08** Actualizar handlers GET/PATCH/DELETE de `app/modules/users/router.py`
  - GET `/{user_id}`: usa `Depends(get_user_for_admin_get)`; remover la llamada directa a `get_user_by_id`
  - PATCH `/{user_id}`: usa `Depends(get_user_for_admin_patch)`; pasa `target` a `service.update_user`
  - DELETE `/{user_id}`: usa `Depends(get_user_for_admin_delete)`; pasa `target` a `service.deactivate_user`
  - Mantener los checks de policy in-router existentes (self-deactivation 409, admin-modifies-superadmin 403, role hierarchy 403)
  - Files: `app/modules/users/router.py`
  - Acceptance: Tres handlers usan la nueva Depends; las llamadas al servicio pasan el parámetro `target`
  - Test: `uv run pytest tests/integration/test_users_integration.py::test_admin_a_never_access_tenant_b_resources -v`
  - Dependencies: T-PRA.03, T-PRA.06, T-PRA.07
  - Size: M
  - Spec: R01, R02, R03, R04

### 2.4 Router wiring: `app/modules/tenants/router.py`

- [x] **T-PRA.09** Actualizar handler GET de `app/modules/tenants/router.py`
  - GET `/{tenant_id}`: usa `Depends(get_tenant_for_admin_get)`; remover los inline 404 checks en líneas 64-66 y 71-76
  - Files: `app/modules/tenants/router.py`
  - Acceptance: Handler usa la nueva Depends; inline 404 checks removidos
  - Test: `uv run pytest tests/integration/test_tenants_integration.py::test_cross_tenant_isolation_complete -v`
  - Dependencies: T-PRA.04
  - Size: S
  - Spec: R01 (tenants), RK-6

### 2.5 Test updates

- [x] **T-PRA.10** Actualizar `tests/integration/test_tenants_integration.py:406` de 404 a 403
  - Según RK-6: contrato unificado significa que GET cross-tenant tenant devuelve 403, no 404
  - Files: `tests/integration/test_tenants_integration.py`
  - Acceptance: `assert resp.status_code == 403` en línea 406; test pasa
  - Test: `uv run pytest tests/integration/test_tenants_integration.py -v`
  - Dependencies: T-PRA.09
  - Size: S
  - Spec: R01 (tenants), RK-6

- [x] **T-PRA.11** Añadir unit tests para `get_user_for_admin` (4 cases)
  - `test_get_user_for_admin_returns_row_on_match` — same tenant
  - `test_get_user_for_admin_raises_403_on_tenant_mismatch` — non-superadmin, cross-tenant
  - `test_get_user_for_admin_returns_row_for_superadmin` — superadmin
  - `test_get_user_for_admin_raises_404_on_missing_row` — id no existente
  - Files: `tests/unit/test_dependencies.py`
  - Acceptance: Los 4 tests pasan
  - Test: `uv run pytest tests/unit/test_dependencies.py -v -k user_for_admin`
  - Dependencies: T-PRA.02
  - Size: M
  - Spec: R01, R04, R05

- [x] **T-PRA.12** Añadir unit tests para `get_tenant_for_admin` (3 cases)
  - `test_get_tenant_for_admin_returns_own_tenant` — same-tenant
  - `test_get_tenant_for_admin_returns_403_for_cross_tenant` — non-superadmin, cross-tenant (NO 404)
  - `test_get_tenant_for_admin_returns_row_for_superadmin` — superadmin
  - Files: `tests/unit/test_dependencies.py`
  - Acceptance: Los 3 tests pasan
  - Test: `uv run pytest tests/unit/test_dependencies.py -v -k tenant_for_admin`
  - Dependencies: T-PRA.04
  - Size: M
  - Spec: R01 (tenants), RK-6

- [x] **T-PRA.13** Añadir unit test para `_log_cross_tenant_attempt`
  - Asserts la log call tiene `caller_id`, `target_id`, `method`, `endpoint`; NO `tenant_id`
  - Files: `tests/unit/test_dependencies.py`
  - Acceptance: Test pasa; verifica exactamente 4 fields
  - Test: `uv run pytest tests/unit/test_dependencies.py -v -k log_cross_tenant`
  - Dependencies: T-PRA.01
  - Size: S
  - Spec: OQ-1 (decisions)

- [x] **T-PRA.VERIFY** PR-A verification — full integration suite
  - Run: `uv run pytest tests/integration/ -v`
  - Acceptance: 0 fallos (los 4 tests objetivo pasan, sin regresiones)
  - Test: full integration suite green
  - Dependencies: T-PRA.08, T-PRA.09, T-PRA.10
  - Size: S
  - Spec: R10

---

## Phase 3: PR-B — Email 409 translation

**Goal:** Email duplicado en `POST /api/v1/users/` devuelve 409 incluso bajo insert concurrente. `create_user` traduce `IntegrityError` con `pgcode='23505'` a `UserError(409)`, hace rollback de la sesión fallida, y propaga otras variantes de `IntegrityError` sin cambios.

- [x] **T-PRB.01** Añadir `try/except IntegrityError` alrededor de `db.flush()` en `create_user`
  - Envolver `await db.flush()` en `try/except IntegrityError`
  - Chequear `getattr(exc.orig, "pgcode", None) == "23505"`
  - En match: `await db.rollback()` después `raise UserError("El email ya está registrado", status_code=409) from exc`
  - En mismatch: `raise` (propaga el original)
  - Añadir comentario de código nombrando el supuesto asyncpg-específico de `pgcode`
  - Files: `app/modules/users/service.py` (alrededor de línea 67 en `create_user`)
  - Acceptance: try/except block en su lugar; rollback dispara antes del raise; errores non-23505 se propagan
  - Test: `uv run pytest tests/integration/test_users_integration.py::test_email_unique_globally_returns_409 -v`
  - Dependencies: none (PR-B puede aterrizar independientemente del runtime de PR-A, pero debe aterrizar después de PR-A para evitar rebase churn en `service.py`)
  - Size: S
  - Spec: R07, R08, R09

- [x] **T-PRB.02** Añadir unit test para traducción 23505
  - Mock `db.flush()` para que eleve `IntegrityError` con `pgcode='23505'`
  - Assert `UserError` con `status_code=409` se eleva
  - Assert `db.rollback()` fue llamado antes del raise
  - Files: `tests/unit/test_users_service.py`
  - Acceptance: Test pasa
  - Test: `uv run pytest tests/unit/test_users_service.py -v -k translates_unique`
  - Dependencies: T-PRB.01
  - Size: S
  - Spec: R07, R08

- [x] **T-PRB.03** Añadir unit test para propagación de IntegrityError non-23505
  - Mock `db.flush()` para que eleve `IntegrityError` con `pgcode='23503'` (FK violation)
  - Assert el `IntegrityError` original se propaga (NO traducido a 409)
  - Files: `tests/unit/test_users_service.py`
  - Acceptance: Test pasa; `UserError(409)` NO se eleva
  - Test: `uv run pytest tests/unit/test_users_service.py -v -k propagates_non_unique`
  - Dependencies: T-PRB.01
  - Size: S
  - Spec: R08

- [x] **T-PRB.04** Añadir test de regresión para rollback-no-envenena-sesión
  - Dos user creations en la misma sesión: la primera es duplicado (espera 409), la segunda es no-duplicado (espera 201)
  - Si rollback falta, la segunda llamada eleva `PendingRollbackError`
  - Files: `tests/unit/test_users_service.py` (o integration test)
  - Acceptance: Ambas llamadas tienen éxito; el segundo usuario queda persistido
  - Test: `uv run pytest tests/unit/test_users_service.py -v -k rolls_back`
  - Dependencies: T-PRB.01
  - Size: S
  - Spec: R09

- [x] **T-PRB.VERIFY** PR-B verification — full integration suite
  - Run: `uv run pytest tests/integration/ -v`
  - Acceptance: Todos los tests verdes (email 409 test pasa, sin regresiones de PR-A o PR-B)
  - Test: full integration suite green
  - Dependencies: T-PRB.01, T-PRB.02, T-PRB.03, T-PRB.04
  - Size: S
  - Spec: R10

---

## Risk Callouts

- **T-PRA.05–T-PRA.07 (cambio de signature de servicio):** Riesgo RK-1. El cambio de signature en `update_user` y `deactivate_user` es un breaking change duro. Los únicos callers conocidos son `app/modules/users/router.py` (actualizado en T-PRA.08) y `app/modules/tenants/router.py` (no importa estos). Un grep antes de PR-A confirma que no hay otros callers.
- **T-PRA.02 (patrón de elevación):** Riesgo RK-2. El par `set_config(..., true)` SET LOCAL es no-negociable. El bloque `try/finally` garantiza que el restore corre incluso en excepción. Un comentario de código debe nombrar la garantía de `SET LOCAL` y la dependencia de rollback.
- **T-PRB.01 (pgcode check):** Riesgo RK-3. `e.orig.pgcode` es asyncpg-específico. El código usa `getattr(exc.orig, "pgcode", None) == "23505"` así que un atributo faltante cae a `raise` (sin mis-traducción silenciosa). El comentario nombra el supuesto asyncpg.
- **T-PRA.09–T-PRA.10 (tenants 404 → 403):** Riesgo RK-6. El cambio de test en línea 406 es la decisión explícita del usuario para unificar la señal de audit. La descripción del PR debe llamar esto out para prevenir que los reviewers lo reviertan.
- **PR-0 prerequisito:** T-PR0.01 DEBE mergear antes de que las tareas T-PRA.* corran. El patrón de elevación en la nueva Depends depende de las garantías de sesión RLS que PR-0 establece.

## Implementation Order

1. **PR-0** (T-PR0.01 → T-PR0.02 → T-PR0.VERIFY): commit prerequisito, sin cambio de diseño
2. **PR-A** (T-PRA.01 → T-PRA.13 → T-PRA.VERIFY): foundation primero (Depends), después service split, después router wiring, después tests
3. **PR-B** (T-PRB.01 → T-PRB.04 → T-PRB.VERIFY): un único try/except en `create_user` + 3 unit tests

PR-A DEBE aterrizar antes que PR-B para estabilizar `app/modules/users/service.py` y evitar rebase churn, pero no son runtime-dependent.

## Spec Requirement Mapping

| Task | Spec Requirement |
|------|------------------|
| T-PR0.01, T-PR0.02 | (prerequisito; enables R10) |
| T-PRA.01 | OQ-1 (log fields) |
| T-PRA.02, T-PRA.03 | R01, R02, R03, R04, R05 |
| T-PRA.04 | R01 (tenants), RK-6 |
| T-PRA.05 | R04 (OQ-3 split) |
| T-PRA.06 | R02, R04, RK-7 |
| T-PRA.07 | R03, R04, RK-7 |
| T-PRA.08 | R01, R02, R03, R04 |
| T-PRA.09 | R01 (tenants), RK-6 |
| T-PRA.10 | R01 (tenants), RK-6 |
| T-PRA.11 | R01, R04, R05 |
| T-PRA.12 | R01 (tenants), RK-6 |
| T-PRA.13 | OQ-1 (decisions) |
| T-PRA.VERIFY | R10 |
| T-PRB.01 | R07, R08, R09 |
| T-PRB.02 | R07, R08 |
| T-PRB.03 | R08 |
| T-PRB.04 | R09 |
| T-PRB.VERIFY | R10 |
