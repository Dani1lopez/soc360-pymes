# Propuesta: fix-f1-remaining-rls-403-and-email-409

## Intención

Cerrar los últimos 4 tests de integración fallando en `fix/heal-f1` para dejar la rama verde antes de mergear. Los 3 tests RLS-403 (#1, #2, #4) asumen que acceso cross-tenant y PATCH de superadmin devuelven 403, pero la policy `rls_users` actual filtra la fila invisible, así que la capa de servicio devuelve 404. El test de email-409 (#3) espera 409 en email duplicado, pero el pre-check de `_is_email_taken` tiene una carrera TOCTOU y la UNIQUE constraint de la DB dispara sin catch como 500. Ninguno es un bug de correctness en producción; son desalineaciones entre tests y contrato RLS (casos RLS) y un traductor de excepciones faltante (caso email).

El cambio debe ser quirúrgico: 6 commits de cleanup ya aterrizaron en esta rama (commit 7007cbf), y el trabajo sin commitear de RLS session poisoning ya bajó los fallos de 7 a 4. Esta propuesta cubre solo los 4 restantes.

## Alcance

### In Scope

- Decidir y aplicar una aproximación por cluster de fallos:
  - **Cluster A (RLS 403 vs 404, tests #1, #2, #4)** — elegir Opción A (alinear tests) u Opción B (pre-check en capa de servicio).
  - **Cluster B (email 409, test #3)** — elegir Opción A (try/except IntegrityError), Opción B (savepoint wrapper), u Opción C (UNIQUE parcial por tenant — listada por completitud, NO recomendada porque el test `test_email_unique_globally_returns_409` afirma unicidad global).
- Actualizar los 3 tests afectados por RLS y el 1 test de email para que pasen.
- Mantener intactos los 3 archivos sin commitear (database.py / dependencies.py / test_auth_login_event_flow.py — el fix de RLS session poisoning); esta propuesta no los re-cubre.

### Out of Scope

- Cualquier cambio a las policies RLS en `migrations/versions/20260312_2052_initial_schema_712a827b0929.py:94-118`.
- Cualquier trabajo de F2 (`openspec/changes/prd-v2-vertical-f2/`).
- Reescribir el módulo de users más allá del mínimo necesario para traducir IntegrityError a 409 (si se elige Opción A/B para email) o para añadir un pre-check de tenant mismatch (si se elige Opción B para RLS).
- Cambiar la semántica de producto de unicidad de email (sigue global según el contrato del test).
- Nuevas migraciones a menos que el usuario solicite explícitamente Opción C.
- Refactor de `_is_email_taken` más allá del mínimo necesario.

## Capacidades

### Nuevas Capacidades

Ninguna.

### Capacidades Modificadas

- `user-management` (existente): el requisito `GET/PATCH/DELETE sobre usuario de otro tenant devuelve 403` puede reinterpretarse como `404 porque RLS oculta la fila` (si Opción A) O enforcedse en la capa de servicio con un tenant-match check explícito (si Opción B). El contrato del test es la fuente de verdad — la opción que se elija, el comportamiento documentado de acceso cross-tenant en la capacidad user-management debe actualizarse para coincidir.
- `user-management`: el requisito `email duplicado en create devuelve 409` ya existe; solo se corrige el gap de implementación (falta el handler de IntegrityError). Sin cambio a nivel de spec si Opción A/B; si Opción C, el requisito mismo cambia de `globalmente único` a `único por tenant`.

## Opciones de Aproximación

### Cluster A — RLS 403 vs 404 (tests #1, #2, #4)

**Opción A — Alinear tests con el diseño RLS actual (cambio solo en tests)**
Cambiar las 4 ocurrencias de `assert == 403` a `assert == 404` en:
- `tests/integration/test_tenants_integration.py:382` (1 ocurrencia)
- `tests/integration/test_users_integration.py:280` (3 ocurrencias para GET / PATCH / DELETE)

Sin cambios en código de producción. RLS es la fuente de verdad y la policy `tenant_id::text = current_setting('app.current_tenant', TRUE)` ya devuelve UNKNOWN para filas cross-tenant, que Postgres trata como "no visible". El path 404 del router es por lo tanto el comportamiento correcto e intencional. También es consistente con `test_tenants_integration.py:406` que ya espera 404 para `GET /tenants/{id}` cross-tenant bajo RLS.

- **Pro 1**: Diff mínimo posible (~4 líneas en tests, sin cambio de producción). Cero riesgo de regresión en flujos de cara al usuario.
- **Pro 2**: Coherente con la filosofía de diseño RLS existente — protección en la capa de framework, no duplicada en código de app. Evita una clase futura de bugs donde el pre-check Python y la policy DB se desincronicen.
- **Con 1**: Pierde el contrato explícito 403. Auditores/reviewers de seguridad que grepean `403` para verificar aislamiento de tenant no lo encontrarán en el path de user-management.
- **Con 2**: 404 filtra menos información que 403, lo cual es bueno para seguridad, pero una necesidad futura de loguear acceso cross-tenant como un intento potencial de privilege-escalation requerirá una señal diferente (ej. un check de `tenant_id` mismatch en la capa de audit log).

**Opción B — Re-arquitecturar la capa de servicio para enforced tenant checks en Python antes de RLS**
Añadir un parámetro `current_user: User` a `get_user_by_id`, `update_user` (y `deactivate_user`); comparar `current_user.tenant_id` con el `tenant_id` del usuario target y raise 403 en mismatch antes de cualquier SELECT. Requiere elevar la sesión de request a un rol superadmin de DB (similar al fix sin commitear en `app/dependencies.py`) para que el pre-check pueda leer la fila target; de lo contrario el SELECT mismo devolverá None bajo RLS y el check es inalcanzable.

- **Pro 1**: Restaura el contrato explícito 403. Acceso cross-tenant se convierte en un evento logueado y distinguible en código de app.
- **Pro 2**: Hace la policy de tenant-isolation explícita en la capa de servicio, que es el lugar convencional donde futuros engineers buscarán reglas de autorización.
- **Con 1**: Refactor mayor — toca `app/modules/users/service.py`, el user router, y 3 tests. By-pasea la propiedad de RLS de "ningún código de app puede leakear cross tenants" elevando a sesión superadmin solo para el check de auth, lo cual expande la superficie de bypass.
- **Con 2**: Duplica la protección: código de app chequea tenant_id Y RLS sigue filtrando filas. Dos fuentes de verdad que deben mantenerse sincronizadas. Riesgo de regresión cuando se añadan endpoints nuevos y olviden el pre-check Python.

### Cluster B — Email 409 (test #3)

**Opción A — Try/except IntegrityError alrededor de `db.flush()` en `create_user`**
Después de `db.add(user)` y `await db.flush()`, envolver el flush en `try/except IntegrityError`, inspeccionar `e.orig.pgcode == '23505'`, re-raise como `UserError("El email ya está registrado", status_code=409)`. ~5 líneas, sin migración.

- **Pro 1**: Quirúrgico, sin migración, sin cambio de test, corrige el bug de producción real (un duplicado concurrente haría 500 hoy). El pre-check en `_is_email_taken` sigue ayudando el caso común.
- **Pro 2**: Suficientemente genérico para reusarse en cualquier UNIQUE constraint futura que añadamos a users.
- **Con 1**: Depende de que `e.orig.pgcode` esté poblado; si asyncpg cambia la shape de su excepción el código rompe silenciosamente. Debería añadir un comentario de que `pgcode` es asyncpg-específico.
- **Con 2**: La sesión queda en estado fallido tras `IntegrityError` en flush; hace falta `await db.rollback()` antes de raise la nueva excepción, de lo contrario la siguiente operación en el mismo request también fallará. Esta es la parte sutil — fácil de olvidar.

**Opción B — SAVEPOINT wrapper alrededor del INSERT**
Misma lógica que A pero usa `async with db.begin_nested():` para que el rollback quede scoped al savepoint y la transacción exterior quede limpia. Semánticas marginalmente más limpias para operaciones anidadas.

- **Pro 1**: Igual que A, pero las semánticas de rollback las garantiza SQLAlchemy en vez de `db.rollback()` manual.
- **Pro 2**: Future-proof si la función crece para hacer múltiples writes donde rollback parcial importa.
- **Con 1**: Un round-trip extra para setear el savepoint; medible solo a QPS muy altos, que el path de creación de usuarios no es.
- **Con 2**: Más código, más conceptos que enseñar en la función.

**Opción C — UNIQUE parcial por tenant sobre email**
Soltar el `users_email_key` global, añadir `CREATE UNIQUE INDEX ... ON users (lower(email)) WHERE tenant_id IS NOT NULL` más un índice único separado para superadmins. Requiere migración alembic y cambia el contrato de producto — `test_email_unique_globally_returns_409` tendría que actualizarse porque el nombre del test afirma unicidad global.

- **Pro 1**: Permite que dos tenants distintos usen el mismo email (común en B2B SaaS donde la misma persona puede pertenecer a múltiples tenants).
- **Con 1**: Cambia un invariante de producto. Out of scope para "fix tests" y el nombre del test lo contradice explícitamente.
- **Con 2**: Riesgo de migración, más el nuevo contrato de test es una decisión de producto que el usuario no ha aprobado.

## Recomendación

Sin recomendación. El usuario pidió explícitamente pros y contras para elegir. El orchestrator debe correr una ronda de preguntas, después volver para finalizar las opciones elegidas en la propuesta antes de la fase de spec.

Si se forzara a elegir defaults, la combinación más probable es **Cluster A → Opción A** (diff mínimo, consistente con el patrón RLS existente en `test_tenants_integration.py:406`) y **Cluster B → Opción A** (diff mínimo que corrige un bug real, sin migración).

## Preguntas Abiertas — Ronda Pre-Proposal

1. **Unicidad de email (regla de producto del Cluster B):** ¿Es "email globalmente único" un requisito de producto duro, o es un artefacto del schema original y el usuario está abierto a relajarlo a unicidad por tenant en un cambio futuro? Esto determina si la Opción C es alguna vez viable.
2. **Señalización de acceso cross-tenant (audit/compliance del Cluster A):** ¿Algún requisito de audit, compliance o seguridad exige que acceso cross-tenant produzca un 403 explícito en respuestas HTTP (en vez de 404) para que aparezca como señal distinta en access logs?
3. **PATCH/DELETE cross-tenant (edge case del Cluster A):** ¿Es 404 aceptable para GET / PATCH / DELETE cross-tenant, o el 404 debería reservarse para "la fila no existe" mientras que acceso cross-tenant recibe un código diferente (ej. 404 con un log line diferente, o 403)?
4. **Frontera de PRs:** ¿Deben aterrizar los 4 fixes en un solo PR sobre `fix/heal-f1`, o deberíamos partir en (a) PR de alineación de tests RLS + (b) PR de email 409? La segunda es más limpia de review pero más lenta.
5. **Alcance del primer slice:** Si tenemos que cortar, ¿cuál subset es el MVP — solo RLS, solo email, o los cuatro? El usuario ya aceptó el trabajo sin commitear de RLS session poisoning; ¿cuál es el mínimo para dar `fix/heal-f1` por hecho?

## Riesgos

| Riesgo | Likelihood | Mitigation |
|--------|------------|------------|
| El usuario elige Opción B para Cluster A y el refactor de capa de servicio rompe un flow que funciona | Media | Correr la suite completa de integración (no solo los 4 tests objetivo) antes de commit. El refactor está contenido a `app/modules/users/service.py` + el user router. |
| Opción A para Cluster B deja la sesión en mal estado porque se olvidan `db.rollback()` tras `IntegrityError` | Baja–Media | Añadir un test de regresión que haga dos user creations en el mismo request: un duplicado, después un no-duplicado. El no-duplicado debe tener éxito. |
| El campo `pgcode` en `IntegrityError.orig` es asyncpg-específico y puede cambiar de forma | Baja | Pin la dependencia y añadir un comentario nombrando el supuesto. |
| El usuario espera una recomendación y empuja cuando no se da | Baja | Esta propuesta dice explícitamente "sin recomendación" upfront; la ronda de preguntas es el camino a una decisión. |

## Plan de Rollback

Cada opción es independientemente revertible:
- **Cluster A Opción A**: revertir los cambios de tests (4 líneas).
- **Cluster A Opción B**: revertir los cambios de capa de servicio y router; los tests vuelven a fallar.
- **Cluster B Opciones A/B**: revertir el cambio en `create_user`; el test #3 vuelve a fallar.
- Sin migraciones en el path recomendado → no se necesita rollback a nivel DB.
- Si se añade una migración (solo si se elige Cluster B Opción C), `alembic downgrade()` es el rollback.

## Dependencias

- Los 3 archivos sin commitear de RLS session poisoning (`app/core/database.py`, `app/dependencies.py`, `tests/integration/test_auth_login_event_flow.py`) deben commitearse primero o como parte del mismo PR. Son el prerequisito que permite que cualquiera de los 4 tests objetivo corra en la sesión de DB correcta.
- Sin cambios de librerías externas.

## Criterios de Éxito

- [ ] Los 4 tests de integración objetivo pasan en `fix/heal-f1`.
- [ ] La suite completa de integración está verde (ningún otro test roto).
- [ ] Sin policy RLS nueva ni migración nueva en el path recomendado.
- [ ] La aproximación elegida está documentada en el código (un comentario en `create_user` para Opción A/B explicando el handler de IntegrityError, y/o un comentario en los tests afectados explicando el contrato 404 para Cluster A).
- [ ] El fix de RLS session poisoning está commiteado como parte del mismo PR (o ya en la rama).
