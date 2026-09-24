# Design: Slice 2 — Scans

## Technical Approach

Este slice añade el CRUD vertical de `Scan` sobre el modelo y la tabla existentes, sin introducir ejecución. La implementación seguirá la separación ya aplicada en Assets: schemas Pydantic, funciones asíncronas de servicio y router FastAPI bajo `/api/v1/scans`. Se reutilizan expresamente las decisiones padre D-002 (servicio async), D-003/D-004 (unión discriminada y validación efectiva), D-005 (eventos post-commit), D-006 (allowlists RBAC), D-007 (scoping tenant), D-008 (paginación), D-009 (whitelist) y D-010 (tests tenant-aware); no se redefinen esos mecanismos compartidos.

El flujo de escritura será request discriminada/parcial → allowlist RBAC → resolución explícita del tenant → validación del asset visible → validación del `config` efectivo → `flush` → `commit` → publicación en `scan.events`. Crear un scan solo persiste una definición con `status="pending"`, `started_at=NULL` y `completed_at=NULL`; no dispara Nmap, Celery, comandos ni eventos operativos. PATCH combina `type` y `config` enviados con el estado persistido antes de validar, y no permite cambiar asset, tenant o lifecycle.

El aislamiento combina las tres defensas ya presentes: FK compuesta `(asset_id, tenant_id)`, policy `rls_scans` y predicados SQL explícitos para usuarios tenant. `superadmin` sigue una rama deliberadamente global para list/by-id/PATCH/DELETE bajo contexto RLS `app.is_superadmin='true'`, mientras que POST exige `tenant_id` objetivo explícito y comprueba el asset contra ese mismo tenant. Los recursos fuera del alcance visible se responden como `404`, no como `403`.

No se requiere DDL. La entrega de aplicación prevé schemas y servicio nuevos, router y registro en `app/main.py`, tres schemas de evento en `app/event_schemas.py` y tests unitarios/API. El modelo `Scan` y las revisiones históricas permanecen intactos; el override `stream=` y `require_any_role` introducidos en slice 1 se consumen sin modificar sus firmas.

## Decisiones de Diseño

### D-S01: Schema shape de POST como unión discriminada

`POST` usará `ScanCreateRequest`, una unión discriminada por el campo público `type` con exactamente cuatro ramas: `DiscoveryScanCreate`, `VulnerabilityScanCreate`, `WebScanCreate` y `FullScanCreate`. La base común incluirá `tenant_id: UUID`, `asset_id: UUID` y `name: str` no vacío de máximo 255 caracteres. Cada rama tendrá su propio modelo Pydantic de `config`, todos con `ConfigDict(extra="forbid")`:

| Rama | `type` | Config público |
| --- | --- | --- |
| Discovery | `discovery` | `host_discovery: StrictBool` |
| Vulnerability | `vulnerability` | `checks: list[StrictStr]`, no vacía y sin identificadores vacíos |
| Web | `web` | `paths: list[StrictStr]`, no vacía y cada ruta empieza por `/` |
| Full | `full` | los tres campos anteriores |

```python
ScanCreateRequest = Annotated[
    DiscoveryScanCreate | VulnerabilityScanCreate | WebScanCreate | FullScanCreate,
    Field(discriminator="type"),
]
```

La unión evita un schema plano con campos opcionales cuya validez depende de combinaciones implícitas, produce OpenAPI por variante y hace imposible aceptar un quinto tipo antes del servicio. El nombre público `type` se traduce explícitamente a `Scan.scan_type`; `scan_type` no se acepta ni se expone.

PATCH usará un schema separado `ScanUpdate` con `name`, `type` y `config` opcionales y `extra="forbid"`. No incluirá `tenant_id`, `asset_id`, `status`, `started_at` ni `completed_at`. El servicio combinará los campos enviados con el scan persistido para validar el par efectivo `(type, config)`; cambiar solo `type` puede devolver 422 si el config previo no cumple el nuevo tipo.

### D-S02: Servicio Scan async mediante funciones de módulo

`app/modules/scans/service.py` expondrá funciones `async def` de módulo: `create_scan`, `get_scan`, `list_scans`, `update_scan` y `delete_scan`. Recibirán `AsyncSession`, y las mutaciones también `EventBus`; todas recibirán `tenant_id: UUID | None` explícito, donde `None` representa exclusivamente la rama global ya autorizada de `superadmin`. `create_scan` recibe siempre el tenant objetivo concreto.

```python
async def create_scan(
    data: ScanCreateRequest,
    tenant_id: UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Scan: ...
```

No habrá clase con estado, sesión creada internamente ni identidad tomada de globals. Esta decisión aplica el patrón de Assets definido por D-002 y facilita tests con `AsyncMock` y queries inspeccionables.

### D-S03: Validación y normalización de config por scan_type

El servicio tendrá un único helper puro `_validate_scan_config(scan_type: str, config: object) -> dict[str, object]`, invocado en POST y sobre el estado efectivo de PATCH. Aunque Pydantic valida el shape inicial de cada rama POST, el helper es la frontera semántica canónica y protege también PATCH, datos ORM preexistentes y llamadas directas al servicio.

Las claves válidas serán exactamente las de la tabla de D-S01. No se aceptan flags ejecutables de Nmap. La normalización conserva booleanos y devuelve copias nuevas de listas después de verificar strings no vacíos; no añade defaults silenciosos. Los mensajes de `ValueError` serán estables y el router los copiará en `detail` con 422:

| Error | Mensaje contractual |
| --- | --- |
| Config no objeto | `config must be an object for scan_type '<type>'` |
| Clave desconocida | `config.<key> is not allowed for scan_type '<type>'` |
| `host_discovery` ausente | `config.host_discovery is required for scan_type '<type>'` |
| Booleano inválido | `config.host_discovery must be a boolean for scan_type '<type>'` |
| `checks` ausente | `config.checks is required for scan_type '<type>'` |
| Lista checks inválida | `config.checks must be a non-empty list of non-empty strings for scan_type '<type>'` |
| `paths` ausente | `config.paths is required for scan_type '<type>'` |
| Lista paths inválida | `config.paths must be a non-empty list of paths beginning with '/' for scan_type '<type>'` |
| Tipo desconocido | `unknown scan_type '<type>'` |

`discovery` exige `host_discovery`; `vulnerability` exige `checks`; `web` exige `paths`; `full` exige los tres. Los validadores Pydantic específicos usarán reglas equivalentes y errores que identifiquen la clave y el tipo; el helper conserva los mensajes exactos para la validación semántica del servicio.

### D-S04: `IntegrityError` → `AssetScanDuplicateError` → 409

Se reutilizará el patrón de inspección de constraint de Assets: consultar `orig.constraint_name`, después `orig.diag.constraint_name` y finalmente el texto del driver. Las violaciones reconocidas como conflicto de identidad de scan se traducirán a `AssetScanDuplicateError`, y el router mapeará esa excepción de dominio a `409 Conflict`; un `IntegrityError` no reconocido se relanzará para no ocultar fallos operativos.

No se crea ni simula `uq_scans_tenant_asset_name_pending`: dos scans `pending` con el mismo `(tenant_id, asset_id, name)` son válidos. El único unique actual de scans es `uq_scans_id_tenant_id`, por lo que una colisión real será excepcional al generarse UUIDs, pero su traducción queda estable y testeable. `fk_scans_asset_tenant` no se tratará como duplicado: la validación previa del asset la convierte en 404 y una carrera que elimine el asset antes de `flush` se traduce igualmente a `scan asset not found`/404 después de inspeccionar esa constraint. Las constraints futuras solo entrarán en el mapping 409 cuando se nombren y documenten explícitamente.

### D-S05: Eventos CRUD en `scan.events` después del commit

Se añadirán `ScanCreatedEvent`, `ScanUpdatedEvent` y `ScanDeletedEvent` a `app/event_schemas.py`, compartiendo un `ScanType` literal canónico. Se reutilizará `EventBus.publish(event, stream="scan.events")`; no se cambia la firma del bus añadida por D-005/T7 ni se crea otro cliente Redis.

Los payloads serán:

- `scan.created`: `{event_id,event_type,timestamp,scan_id,tenant_id,asset_id,name,type,status,config,created_at}`.
- `scan.updated`: `{event_id,event_type,timestamp,scan_id,tenant_id,changed_fields}`.
- `scan.deleted`: `{event_id,event_type,timestamp,scan_id,tenant_id}`.

Cada mutación ejecuta `flush`, captura el snapshot necesario, hace `commit` exitoso y solo entonces publica. `changed_fields` contiene, en orden público estable, solo campos enviados cuyo valor cambió: `name`, `type`, `config`. Un fallo antes o durante commit no publica. Un fallo Redis posterior al commit se registra y no intenta rollback ni cambia el éxito ya persistido; la atomicidad DB/Redis y un outbox quedan fuera de alcance, igual que en D-005.

### D-S06: RBAC mediante allowlist exacta

Cada endpoint declarará `Depends(require_any_role(...))`, reutilizando D-006 sin checks de rol dentro del servicio:

| Operación | Allowlist |
| --- | --- |
| POST, PATCH, DELETE | `admin`, `superadmin` |
| GET list, GET list filtrado, GET by-id | `admin`, `analyst`, `viewer`, `superadmin` |

`ingestor` está denegado en las seis operaciones y recibe 403 antes de evaluar existencia o tenant. `superadmin` solo tiene alcance cross-tenant porque aparece expresamente en la allowlist y porque su contexto RLS lo habilita; no existe autorización jerárquica implícita.

### D-S07: Tenant scoping en tres capas y ruta explícita de superadmin

El aislamiento aplica conjuntamente D-007 y las defensas específicas de scans:

1. `fk_scans_asset_tenant` garantiza en PostgreSQL que scan y asset comparten tenant.
2. `rls_scans` limita filas usando `app.current_tenant` o permite el contexto `app.is_superadmin='true'`.
3. Todas las queries de usuario tenant agregan `Scan.tenant_id == current_user.tenant_id` de forma explícita.

El router resuelve `tenant_id=current_user.tenant_id` para usuarios tenant y `tenant_id=None` para list/by-id/PATCH/DELETE de `superadmin`. Un `None` de un usuario no-superadmin se rechaza defensivamente, nunca se interpreta como consulta global. GET/PATCH/DELETE cross-tenant retornan 404. Para `superadmin`, las queries omiten deliberadamente el predicado tenant y preservan el tenant del scan; POST requiere un `tenant_id` concreto en body. `DBWithTenantDep`/la dependencia tenant-aware debe establecer el contexto RLS antes de consultar.

### D-S08: Validación de referencia Asset en POST y filtro

Antes de crear, el router o un helper de servicio consultará `Asset` por `asset_id` y tenant objetivo. Para un admin tenant, el tenant objetivo es obligatoriamente `current_user.tenant_id`; para `superadmin`, es el `tenant_id` explícito del body. La consulta siempre exige simultáneamente `Asset.id == asset_id` y `Asset.tenant_id == effective_tenant_id`, incluso para superadmin, porque esta validación comprueba coherencia de la relación y no visibilidad global.

Un asset inexistente, no visible o perteneciente a otro tenant devuelve `404 Not Found` con `detail="scan asset not found"`, sin insertar el scan. Este 404 es deliberado y prevalece sobre una interpretación genérica de mismatch como 422: satisface el contrato formal de asociación y evita revelar existencia cross-tenant. Solo errores de forma del UUID, `tenant_id` ausente o mismatch directo entre el body de un usuario tenant y su identidad producen 422.

La misma validación de visibilidad se ejecuta cuando `GET /scans?asset_id=...` incluye filtro: un asset ausente/no visible devuelve 404 en vez de una página vacía. Superadmin puede filtrar por cualquier asset existente.

### D-S09: Whitelist pública exacta de once campos

`ScanResponse` materializará exactamente `id`, `tenant_id`, `asset_id`, `name`, `type`, `status`, `config`, `started_at`, `completed_at`, `created_at` y `updated_at`. Un constructor explícito mapeará `scan_type → type`; el router no devolverá `Scan.__dict__` ni dependerá de serialización ORM implícita.

`status` se incluye porque el cliente necesita observar el lifecycle aunque no pueda mutarlo. `config` se incluye porque forma parte de la definición CRUD y permite editarla coherentemente. Los timestamps operativos se incluyen para que slices de ejecución futuros puedan actualizar el mismo contrato sin alterar esta whitelist. `created_by_user_id`, `raw_input` y cualquier atributo ORM actual o futuro quedan fuera; no existen en el modelo actual y no deben filtrarse automáticamente si se añaden.

### D-S10: Paginación offset/limit y orden determinista

`GET /api/v1/scans` declarará `limit: Query(50, ge=1, le=200)` y `offset: Query(0, ge=0)`. El servicio devolverá `(items, total)` y el router construirá `{items,total,limit,offset}`. `items` se ordena por `Scan.created_at DESC, Scan.id DESC` para desempate estable.

El count y la consulta de items compartirán exactamente los predicados de tenant y `asset_id`; así el filtro afecta también `total`. FastAPI responderá 422 antes del servicio para `limit=0`, `limit=201` u `offset=-1`. La rama superadmin cambia únicamente la ausencia de predicado tenant, no la paginación ni el orden.

### D-S11: El slice no crea una migración Alembic

Este slice se entrega sin revisión nueva. La tabla existente ya contiene todas las columnas públicas y operativas, `chk_scans_scan_type` con los cuatro tipos, `chk_scans_status` con los cinco estados, `uq_scans_id_tenant_id`, índices, trigger `updated_at`, grants y `rls_scans`. La revisión `c1d2e3f4a5b6` ya instaló y validó `fk_scans_asset_tenant` y retiró la FK simple insegura.

Los schemas discriminados, los mensajes 422, la inmutabilidad del lifecycle y la whitelist son contratos de aplicación, no DDL. No se crea una migración vacía y no se editan revisiones históricas. Si una tarea posterior descubre una columna o constraint necesaria, debe volver a proposal/design antes de apply.

### D-S12: Lifecycle de solo lectura en este slice

`create_scan` fijará explícitamente `status="pending"`, `started_at=None` y `completed_at=None`, independientemente de defaults ORM/DB. Los schemas POST y PATCH usan `extra="forbid"`, por lo que cualquier intento de enviar `status`, `started_at` o `completed_at` devuelve 422 y no modifica la fila.

No se implementa state machine, endpoint de trigger/cancelación ni transición manual. Los estados `running`, `completed`, `failed` y `cancelled` continúan válidos a nivel DB y se devuelven en responses para registros actualizados posteriormente por slices 5/6, pero Slice 2 nunca los escribe desde HTTP.

### D-S13: Listado filtrado por `asset_id` como sexta operación

`GET /api/v1/scans?asset_id=<uuid>` comparte ruta y response paginada con el listado general, pero se trata como sexta operación autorizable y testeable. Tras validar que el asset es visible según D-S08, el servicio añade `Scan.asset_id == asset_id` al count y a items, además del scope tenant cuando corresponde.

No se crea `/assets/{id}/scans` ni un sexto path. Un filtro UUID mal formado produce 422 de FastAPI; un UUID válido pero ausente/no visible produce 404; un asset visible sin scans produce 200 con `items=[]` y `total=0`.

### D-S14: Estrategia de tests y fixtures

La implementación seguirá TDD en `tests/unit/test_scans.py` y `tests/api/test_scans.py`, pero esos archivos pertenecen a apply, no a esta fase de diseño. Los tests API reutilizarán `tenant_client`, que usa `httpx.AsyncClient` con ASGI transport, ejecuta `set_tenant_context`, conecta Redis real aislado en `db=14`, sobrescribe `get_event_bus` para mantener una única instancia espiable y limpia Redis/singletons al finalizar. No se asumirá que el fixture `client` plano establece RLS.

La matriz mínima será:

- 30 celdas RBAC: 6 operaciones × 5 roles canónicos.
- GET/PATCH/DELETE cross-tenant con 404 y list/count aislados.
- list/by-id/PATCH/DELETE globales de superadmin y POST con tenant explícito.
- asociación asset válida, inexistente y cross-tenant; también carrera de FK.
- cuatro configs válidos y casos de clave faltante, tipo inválido, lista vacía, string vacío, path sin `/` y clave desconocida.
- PATCH con tipo/config efectivo, rechazo de lifecycle y PATCH sin cambios.
- nombres pending repetidos permitidos y mapping 409 de una constraint reconocida sin inventar unicidad de negocio.
- spies de los tres eventos, payloads, stream, orden commit-before-publish y ausencia de evento si falla commit.
- publicación fallida post-commit sin reversión de la fila.
- paginación, orden, total, filtro por asset y parámetros 422.
- whitelist exacta de once campos en create/get/patch/list.

Los tests unitarios inspeccionarán predicados tenant y asset, helper de config, changed fields, constraint inspection y secuencia transaccional. Los API tests cubrirán los 52 escenarios del spec, agrupando escenarios equivalentes sin reducir la matriz obligatoria.

### D-S15: Contratos de error, archivos y rollout

Los códigos públicos quedan fijados así: POST 201, list/get/patch 200 y DELETE 204 sin body; RBAC denegado 403; recurso no visible/inexistente 404; config, body o query inválidos 422; conflicto de integridad reconocido 409. El router captura únicamente excepciones de dominio/validación conocidas y deja propagar fallos inesperados.

| Archivo | Acción prevista en apply |
| --- | --- |
| `app/modules/scans/schemas.py` | Crear requests discriminadas, PATCH, response y envelope paginado |
| `app/modules/scans/service.py` | Crear CRUD async, validación, scoping, paginación, errores y eventos |
| `app/modules/scans/router.py` | Crear cinco rutas/seis operaciones con RBAC y validación de asset |
| `app/event_schemas.py` | Añadir `ScanType` y tres eventos CRUD |
| `app/main.py` | Importar y registrar `scans_router` bajo `/api/v1` |
| `tests/unit/test_scans.py` | Cubrir helpers y servicio |
| `tests/api/test_scans.py` | Cubrir contrato HTTP y 52 escenarios |
| `app/modules/scans/models.py` | Sin cambios |
| `migrations/versions/*` | Sin cambios |

El rollout es aplicación-only: desplegar código tras verificar que el head Alembic existente incluye `c1d2e3f4a5b6`, ejecutar tests del slice y regresión, y comprobar conectividad a Redis antes de habilitar tráfico. El rollback desregistra/revierte router, schemas, servicio y eventos; no hay downgrade DB y las filas existentes permanecen. Si ya hay consumidores de `scan.events`, su pausa debe coordinarse antes del rollback.

Flujo concreto:

```text
JWT → require_any_role → sesión con contexto RLS
                          ↓
request → tenant objetivo → asset visible/coherente → Scan service
                                                    ↓
                                      PostgreSQL flush + commit
                                                    ↓
                                  EventBus(stream="scan.events")
```

## Migration Plan

No se ejecutará `alembic revision` para Slice 2. Como gate previo al despliegue se comprobará que la base está en un head que contiene las revisiones `8f2c1a4b9d7e` y `c1d2e3f4a5b6`, y que `alembic check` no detecta drift del modelo `Scan`. No se altera ni revierte DDL durante rollout o rollback de este slice.

La verificación de infraestructura confirmará la existencia de `chk_scans_scan_type`, `chk_scans_status`, `uq_scans_id_tenant_id`, `fk_scans_asset_tenant`, `ix_scans_asset_tenant`, trigger `trg_scans_updated_at`, grants y policy `rls_scans`. Cualquier ausencia indica una base mal migrada y bloquea el deploy; no se corrige mediante una revisión vacía del slice.

## Riesgos Específicos del Slice

- POST no equivale a ejecución: clientes podrían interpretar `pending` como trabajo encolado. La documentación y tests deben confirmar que no se publica `scan.requested` ni se invoca executor alguno.
- El cambio parcial de `type` puede invalidar el config persistido. La validación del estado efectivo evita guardar combinaciones incoherentes y devuelve 422 antes del flush.
- RLS y filtros explícitos son complementarios. Usar accidentalmente `tenant_id=None` para un usuario tenant abriría una query global; el router debe reservar ese sentinel a `superadmin` y fallar cerrado en los demás casos.
- La validación previa del asset puede competir con un DELETE concurrente. La FK compuesta sigue siendo la autoridad y su constraint debe mapearse a 404 sin revelar otro tenant.
- Commit y Redis no son atómicos. Una caída tras commit puede dejar una mutación sin evento; se acepta con logging, sin outbox en este slice.
- No existe unicidad de negocio para scans pending. Añadir deduplicación en código o interpretar nombres repetidos como 409 violaría el spec.
- Datos históricos de `config` podrían no cumplir el contrato nuevo. Se pueden leer por whitelist, pero cualquier PATCH los revalida contra el tipo efectivo y puede exigir corregir config en la misma request.
- Una futura FK de Vulnerabilities puede cambiar la semántica de DELETE. Slice 3 debe reevaluar retención/cascade antes de almacenar datos reales dependientes.

## Out of Scope (this slice)

- Nmap y cualquier ejecución de scans; corresponden al slice 5.
- La state machine de status, trigger, cancelación y timestamps operativos; corresponde a slice 5+.
- Celery, Celery Beat, workers, schedules, retries y tareas background; corresponden al slice 6.
- Vulnerability records vinculados a scans, deduplicación y lifecycle de vulnerabilidades; corresponden al slice 3.
- Dashboard, métricas agregadas, cobertura, success rate y caché; corresponden al slice 7.
- Enriquecimiento LLM, proveedores, prompts y OpenRouter; corresponden al slice 8.
- LangGraph, nodos, estados y pipeline de agentes; corresponden al slice 9.
- Cuota `scans_per_day`, que se consumirá al ejecutar/trigger, no al crear una definición.
- Consumidores, webhooks, outbox, export CSV, frontend, PDF, reporting y notificaciones.
- Cambios al modelo `Scan`, tabla `scans` o migraciones históricas.
