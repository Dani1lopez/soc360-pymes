# Propuesta: Slice 2 — Scans

> Delta vertical del [proposal F2 padre](../../proposal.md). Este documento limita la entrega al CRUD de Scans y no redefine la visión ni los nueve slices del cambio `prd-v2-vertical-f2`.

## Propósito

Entregar la superficie CRUD vertical de `Scan` sobre los assets ya disponibles en slice 1, con contratos Pydantic seguros, servicio asíncrono, RBAC, aislamiento multi-tenant y eventos de persistencia. `admin` administra definiciones de scan; `analyst` y `viewer` pueden consultarlas; `superadmin` opera explícitamente cross-tenant; `ingestor` queda denegado. Esta base se construye ahora para que los slices 5 y 6 puedan incorporar ejecución Nmap y scheduling sin mezclar transporte HTTP, persistencia, permisos ni aislamiento con el motor de ejecución.

## Cambios propuestos

- Crear `app/modules/scans/schemas.py` con una unión discriminada de POST para los cuatro tipos persistidos (`discovery`, `vulnerability`, `web`, `full`), usando `type` como campo público y traduciendo a `Scan.scan_type`. Cada variante tendrá un modelo de `config` propio con campos desconocidos prohibidos; la validación semántica por tipo residirá en el servicio.
- Crear un schema PATCH parcial, equivalente al patrón `AssetUpdate`, para `name`, `type` y `config`. `asset_id`, `tenant_id`, `status`, `started_at` y `completed_at` no serán mutables por este endpoint: la identidad y la pertenencia no cambian, y el lifecycle operativo queda reservado a los slices de ejecución.
- Crear responses por whitelist. La respuesta pública incluirá exactamente `id`, `tenant_id`, `asset_id`, `name`, `type`, `status`, `config`, `started_at`, `completed_at`, `created_at` y `updated_at`; no se serializará el objeto ORM ni atributos futuros de forma implícita.
- Crear un servicio asíncrono de CRUD y listado paginado. POST y PATCH validarán el `config` efectivo según el tipo efectivo; las mutaciones usarán `flush → commit → publish`; conflictos de integridad traducibles a conflicto de dominio devolverán `409 Conflict`.
- Crear el router bajo `/api/v1/scans` con POST, GET list, GET by-id, PATCH y DELETE. El listado admitirá filtro opcional `asset_id`; se considera una sexta operación de capacidad para completar la matriz solicitada, aunque reutiliza la misma ruta HTTP y no añade un sexto path.
- Aplicar RBAC mediante allowlists exactas: escritura para `admin` y `superadmin`; lectura para `admin`, `analyst`, `viewer` y `superadmin`; denegación total para `ingestor`.
- Publicar `scan.created`, `scan.updated` y `scan.deleted` en el stream `scan.events`, siempre después de un commit exitoso. Estos eventos describen persistencia CRUD; los eventos operativos `scan.requested`, `scan.started`, `scan.progress`, `scan.completed` y `scan.failed` pertenecen a los slices de ejecución.
- Mantener el aislamiento en tres capas: FK compuesta `(asset_id, tenant_id) → assets(id, tenant_id)`, policy RLS `rls_scans` y predicado explícito de tenant para usuarios tenant. La ruta `superadmin` omitirá el predicado de tenant de forma deliberada bajo contexto RLS de superadmin y exigirá tenant objetivo explícito al crear.
- No incorporar motor de ejecución. Crear un scan lo deja en `pending` y no inicia tareas, procesos ni comandos; en este slice la ejecución es deliberadamente un no-op.

## Capability surface

La superficie pública contiene cinco rutas HTTP y seis operaciones autorizables; la sexta es el listado filtrado por asset sobre el mismo `GET /scans`.

| Operación | Método y ruta | Roles permitidos | Éxito esperado | Errores relevantes |
| --- | --- | --- | --- | --- |
| Crear scan | `POST /api/v1/scans` | `admin`, `superadmin` | `201 Created` | `403`, `404` asset no visible/inexistente, `409`, `422` |
| Listar scans | `GET /api/v1/scans` | `admin`, `analyst`, `viewer`, `superadmin` | `200 OK` | `403`, `422` paginación inválida |
| Listar scans de un asset | `GET /api/v1/scans?asset_id={asset_id}` | `admin`, `analyst`, `viewer`, `superadmin` | `200 OK` | `403`, `404` asset no visible/inexistente, `422` |
| Obtener scan | `GET /api/v1/scans/{id}` | `admin`, `analyst`, `viewer`, `superadmin` | `200 OK` | `403`, `404` |
| Actualizar scan | `PATCH /api/v1/scans/{id}` | `admin`, `superadmin` | `200 OK` | `403`, `404`, `409`, `422` |
| Eliminar scan | `DELETE /api/v1/scans/{id}` | `admin`, `superadmin` | `204 No Content` | `403`, `404`, `409` si existe una dependencia protegida |

Reglas comunes:

- Los listados devuelven `{items, total, limit, offset}`, con `limit=50` por defecto, máximo `200`, y orden determinista por `created_at DESC, id DESC`.
- Para usuarios tenant, todos los reads y writes aplican `Scan.tenant_id == current_user.tenant_id`; un acceso by-id o por `asset_id` fuera del tenant devuelve `404`, no `403`.
- Para `superadmin`, list/by-id/PATCH/DELETE pueden operar globalmente sin predicado explícito de tenant, apoyados en `app.is_superadmin = 'true'`. POST exige `tenant_id` explícito y comprueba que el asset objetivo pertenece al mismo tenant.
- POST fija `status="pending"` y timestamps operativos nulos. Ni POST ni PATCH aceptan que el cliente falsifique estados o timestamps de ejecución.

## Alcance por rol

`✓ own` limita los resultados al tenant autenticado; `✓ cross` permite alcance global únicamente a `superadmin`; `✗` significa `403 Forbidden`. La tabla tiene 6 operaciones × 5 roles canónicos = 30 celdas de decisión.

| Endpoint / operación | admin | analyst | viewer | superadmin | ingestor |
| --- | --- | --- | --- | --- | --- |
| `POST /scans` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |
| `GET /scans` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `GET /scans?asset_id={asset_id}` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `GET /scans/{id}` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `PATCH /scans/{id}` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |
| `DELETE /scans/{id}` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |

## Decisiones de scope

- **Nmap (slice 5):** no se ejecutan comandos ni se interpretan resultados. POST solo persiste una definición en `pending`.
- **Celery, Celery Beat y workers (slice 6):** no se encolan tareas, no hay schedules ni reintentos background.
- **LLM enrichment (slice 8):** `config` no acepta opciones de proveedor, prompt o enriquecimiento; no se invoca OpenRouter.
- **LangGraph (slice 9):** no se crean nodos, estados ni pipelines de agentes.
- **Vulnerabilities (slice 3):** no se crean ni exponen registros de vulnerabilidad desde Scans.
- **Dashboard (slice 7):** no se agregan métricas, cobertura, success rate ni caché.
- **Lifecycle:** `status`, `started_at` y `completed_at` son de solo lectura en esta API. Slice 2 no añade endpoints `/trigger`, `/start`, `/complete`, `/fail` o `/cancel`; las transiciones serán internas al executor/worker cuando esos slices existan.
- **Cuota `scans_per_day`:** no se consume cuota al crear una definición porque no ocurre una ejecución. El enforcement se aplicará al trigger real en el slice que lo introduzca.

## Migración DB

**No se necesita una nueva revisión Alembic para slice 2.** La tabla `scans` ya contiene todos los campos requeridos (`id`, `tenant_id`, `asset_id`, `name`, `scan_type`, `status`, `config`, timestamps), checks para los cuatro tipos y cinco estados, `uq_scans_id_tenant_id`, índices, trigger `updated_at`, grants y policy `rls_scans`. La revisión posterior `c1d2e3f4a5b6` ya reemplazó la FK simple por `fk_scans_asset_tenant`, que garantiza que scan y asset compartan tenant.

La validación discriminada de `config`, la inmutabilidad pública del lifecycle y la whitelist de respuesta son contratos de aplicación y no requieren DDL. Si spec o design posteriores descubren una necesidad real de constraint o columna, deberán elevarla como cambio explícito antes de apply; no se creará una migración vacía.

## Áreas afectadas

| Área | Cambio previsto | Razón |
| --- | --- | --- |
| Schemas de scans | Create/Update/Response/List | Contratos discriminados, PATCH parcial y whitelist |
| Servicio de scans | CRUD async, validación, paginación, errores y eventos | Separar reglas de dominio del router |
| Router de scans y registro API | Cinco rutas bajo `/api/v1/scans` | Exponer la capacidad vertical |
| Schemas de eventos | Tres eventos CRUD tipados | Contrato estable para consumidores futuros |
| Event bus | Reutilización del override de stream existente | Publicar en `scan.events` sin otro cliente Redis |
| Auth/dependencies | Reutilización de allowlist y DB tenant-aware de slice 1 | RBAC exacto y contexto RLS |
| Modelo y migraciones | Sin cambio | El shape y el aislamiento requeridos ya existen |

## Riesgos y supuestos

- **Creación no equivale a ejecución.** Un scan creado queda `pending`; no se publica `scan.requested` ni se simula progreso. La UI o clientes deberán tratarlo como definición pendiente hasta que slice 5/6 añada un trigger real.
- **Lifecycle interno.** Permitir PATCH de `status` ahora permitiría fabricar ejecuciones completadas sin evidencia. Se mantiene read-only y se posponen transiciones y timestamps operativos al executor/worker.
- **Política cross-tenant.** Solo `superadmin` puede leer o mutar scans de cualquier tenant. Incluso en esa ruta, la FK compuesta impide vincular un scan del tenant A con un asset del tenant B.
- **Semántica de `config`.** Los cuatro tipos requieren modelos y validadores separados; el spec deberá fijar sus campos, límites y mensajes de error sin introducir flags de Nmap ejecutables ni opciones inseguras.
- **Commit y Redis no son atómicos.** Como en Assets, un fallo al publicar después del commit no revierte la mutación. Slice 2 acepta este riesgo, registra el fallo y deja un outbox fuera de alcance.
- **Eliminación en cascada.** La FK futura de Vulnerabilities puede hacer que eliminar un scan borre hijos por cascade. Mientras slice 3 está fuera, DELETE conserva el contrato actual; el slice 3 deberá revalidar política de retención antes de exponer datos reales.
- **Ausencia de unicidad de negocio.** La tabla no impide nombres repetidos ni múltiples scans equivalentes para un asset. No se añade una regla de unicidad sin una decisión de producto; los conflictos de constraints existentes sí se traducen de forma estable.

## Rollback

El rollback de aplicación consiste en desregistrar el router de scans y revertir schemas, servicio y eventos del slice. No hay downgrade de base de datos porque no se crea revisión Alembic ni se altera el shape persistido. Los registros `scans` preexistentes permanecen intactos. Si ya existen consumidores de `scan.events`, el rollback debe coordinar su pausa para evitar que esperen eventos CRUD que dejarán de publicarse.

## Criterios de éxito

- Los cinco paths y las seis operaciones documentadas responden con los códigos definidos y la matriz RBAC cubre las 30 combinaciones.
- POST, PATCH y DELETE exitosos publican respectivamente `scan.created`, `scan.updated` y `scan.deleted` en `scan.events`, solo después del commit.
- La validación de POST/PATCH rechaza `config` incompatible con el tipo efectivo y campos desconocidos con `422`.
- Usuarios tenant no pueden observar ni mutar scans o assets de otro tenant; los by-id cross-tenant devuelven `404`.
- `superadmin` puede operar cross-tenant de forma explícita y no puede crear una relación scan/asset entre tenants distintos.
- Las respuestas contienen solo la whitelist declarada y los listados respetan paginación determinista.
- No se ejecuta Nmap, no se encola trabajo y no se modifican estados operativos desde la API del slice.
- Los tests del slice y la suite de regresión pasan bajo `strict_tdd: true`, sin requerir una migración nueva.

## Fuera de alcance

- No se implementa Nmap ni cualquier otro motor de ejecución; corresponde al slice 5.
- No se implementan Celery, Celery Beat, workers, schedules ni tareas background; corresponden al slice 6.
- No se implementa enriquecimiento LLM ni integración con OpenRouter; corresponde al slice 8.
- No se implementa LangGraph ni pipeline de agentes; corresponde al slice 9.
- No se crean, deduplican ni gestionan vulnerabilidades vinculadas a scans; corresponde al slice 3.
- No se calculan dashboard, métricas agregadas, cobertura ni success rate; corresponde al slice 7.
- No se añaden endpoints de trigger, cancelación o transición de lifecycle.
- No se consumen eventos ni se implementan webhooks; este slice solo publica los tres eventos CRUD.
- No se añade export CSV, frontend, PDF, reporting ni notificaciones.
- No se modifica el modelo `Scan`, la tabla `scans` ni migraciones históricas.
