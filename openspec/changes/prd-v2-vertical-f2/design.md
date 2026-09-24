# Design: Slice 1 — Assets

## Technical Approach

Este slice combina una migración Alembic reversible con el primer módulo CRUD vertical de F2. La migración alinea `app/modules/assets/models.py` y la tabla `assets`: `name` pasa a `value`, desaparece `hostname`, se amplían los tipos permitidos y se incorpora unicidad por tenant, tipo y valor. La migración existente `migrations/versions/20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py` se conserva como historia inmutable; se crea una revisión nueva sobre el head actual.

El módulo seguirá la separación de F1: schemas, servicio y router, tomando como referencia `app/modules/tenants/schemas.py`, `app/modules/tenants/service.py:108` y `app/modules/tenants/router.py:19`. La autenticación, las sesiones con contexto RLS y los guards reutilizan `app/dependencies/auth.py`, `app/dependencies/db_deps.py` y los aliases de `app/dependencies/__init__.py`; el router se registrará bajo `/api/v1`, como los routers F1 en `app/main.py:261-263`.

`AssetService` será asíncrono. Aunque las validaciones puras son síncronas, todas las operaciones públicas esperan I/O de `AsyncSession` y, en mutaciones, de Redis Streams. Se mantiene así el patrón real de F1 (`async def` en `app/modules/tenants/service.py`) y se evita introducir sesiones síncronas o thread pools sin necesidad.

El flujo de escritura será request validada → RBAC → contexto y filtro tenant → servicio → `flush`/`commit` → publicación. El flujo de lectura aplicará simultáneamente RLS y predicados SQL explícitos. No se implementan consumidores: `asset.created`, `asset.updated` y `asset.deleted` quedan como contratos para slices posteriores.

## Decisiones de Diseño

### D-001: Forma de la migración Alembic

Se creará una revisión nueva sobre el head único. `upgrade()` usará `op.alter_column("assets", "name", new_column_name="value")`, `op.drop_column` para `hostname`, eliminará y recreará `chk_assets_asset_type`, y añadirá `uq_assets_tenant_type_value`. No se editará la revisión histórica de junio.

El orden evita que el constraint antiguo rechace el mapping de datos `host` → `hostname`: primero se elimina el check, luego se actualizan filas, después se crea el check nuevo. Antes del unique se ejecuta una precondición SQL que aborta con un mensaje explícito si existen duplicados.

```python
op.drop_constraint("chk_assets_asset_type", "assets", type_="check")
op.alter_column("assets", "name", new_column_name="value")
op.drop_column("assets", "hostname")
op.execute("UPDATE assets SET asset_type='hostname' WHERE asset_type='host'")
op.create_check_constraint("chk_assets_asset_type", "assets", NEW_TYPES_SQL)
op.create_unique_constraint(
    "uq_assets_tenant_type_value", "assets", ["tenant_id", "asset_type", "value"]
)
```

`downgrade()` hará el inverso explícito, pero **solo si la BD no contiene filas con `asset_type IN ('subnet', 'cloud_resource')`**. Antes del primer DDL ejecutará una precondición `WHERE asset_type IN ('subnet', 'cloud_resource')` que cuenta filas con `op.get_bind().execute(...).scalar_one()`; si el resultado es distinto de cero, lanza `RuntimeError(...)` con mensaje accionable (tipos afectados y cuenta) y aborta antes de cualquier DDL. Solo si la cuenta es cero seguirá el `downgrade()`: eliminar `uq_assets_tenant_type_value`, eliminar el check de seis tipos, mapear `hostname` a `host`, recrear la columna nullable `hostname` sin recuperar contenido, renombrar `value` a `name` y restaurar `chk_assets_asset_type` con `host`, `domain`, `ip`, `web_app`. El downgrade preserva filas y el antiguo `name`, pero la pérdida del contenido de la columna eliminada es deliberada y documentada. La regla es “todo o nada”: o completa todo el DDL o aborta antes del primero con el `RuntimeError`; no hay ejecuciones parciales.

### D-002: `AssetService` será asíncrono

Las funciones de `app/modules/assets/service.py` serán `async def` y recibirán `AsyncSession`, igual que `app/modules/tenants/service.py:108-218`. El servicio no creará sesiones ni extraerá identidad desde globals; sus dependencias se pasan explícitamente para facilitar tests unitarios.

```python
async def create_asset(
    data: AssetCreateRequest,
    tenant_id: UUID,
    db: AsyncSession,
    event_bus: EventBus,
) -> Asset: ...
```

Las validaciones puras pueden ser helpers síncronos privados. No se crea una clase con estado: el patrón F1 actual usa funciones de módulo y es suficiente para este slice.

### D-003: Unión discriminada para creación y schema separado para PATCH

`POST` usará una unión discriminada por el campo público `type`, con un schema por tipo. Esto hace explícitos los seis contratos y permite extender reglas por tipo sin un `if` monolítico en el router. Internamente, `type` se traduce a `Asset.asset_type`; el nombre de columna no se expone como `asset_type` en la API.

```python
class AssetCreateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    value: str = Field(min_length=1, max_length=255)

class IpAssetCreate(AssetCreateBase):
    type: Literal["ip"]

AssetCreateRequest = Annotated[
    HostnameAssetCreate | DomainAssetCreate | IpAssetCreate |
    WebAppAssetCreate | SubnetAssetCreate | CloudResourceAssetCreate,
    Field(discriminator="type"),
]
```

`PATCH` usará `AssetUpdate(type: AssetType | None, value: str | None)` con `extra="forbid"`. El servicio combina los campos enviados con el estado persistido y valida el par resultante; así se soportan updates parciales sin una unión ambigua.

### D-004: Validación semántica por tipo en el service

La validación específica vivirá en `app/modules/assets/service.py`, tal como exige el spec; Pydantic se limita a shape, discriminator, longitud y campos desconocidos. Un único helper `_validate_asset_value(asset_type, value)` se ejecutará en POST y sobre el estado efectivo de PATCH, devolviendo el valor normalizado o levantando un error 422 estable.

| Tipo | Validador elegido | Normalización |
| --- | --- | --- |
| `ip` | `ipaddress.ip_address` | representación comprimida canónica IPv4/IPv6 |
| `domain` | regex FQDN por labels | lowercase y sin punto final |
| `hostname` | regex RFC 1123 sin obligación de punto | lowercase |
| `web_app` | `pydantic.HttpUrl` | string URL normalizada; solo `http`/`https` |
| `subnet` | `ipaddress.ip_network(..., strict=False)` | network address CIDR canónica |
| `cloud_resource` | regex AWS ARN anclada | conserva case del resource |

Los mensajes requeridos serán exactos: IP inválida produce `value must be a valid IPv4 or IPv6 address`, FQDN inválido `value must be a valid FQDN` y CIDR inválido `value must be a valid CIDR`. La regex ARN aceptará como mínimo `arn:partition:service:region:account-id:resource`, incluido `arn:aws:s3:::my-bucket`.

### D-005: Publicación en Redis Streams después del commit

Se reutilizarán `app/event_bus/EventBus` y `app/dependencies/event_deps.py`; no se crea otro cliente Redis. `EventBus.publish` admitirá un override opcional de stream para mantener el comportamiento F1 por defecto y permitir el stream exigido `asset.events` en este módulo.

```python
class AssetCreatedEvent(BaseEvent):
    event_type: Literal["asset.created"] = "asset.created"
    asset_id: UUID
    type: AssetType
    value: str
    created_at: datetime

await event_bus.publish(event, stream="asset.events")
```

Los payloads serán: created `{event_id,event_type,timestamp,asset_id,tenant_id,type,value,created_at}`, updated `{event_id,event_type,timestamp,asset_id,tenant_id,changed_fields}` y deleted `{event_id,event_type,timestamp,asset_id,tenant_id}`. `changed_fields` será una lista ordenada de nombres públicos (`type`, `value`).

La mutación se hace `flush`, se captura el snapshot del evento, se ejecuta `await db.commit()` y solo entonces se publica, evitando eventos fantasma de transacciones revertidas. No se introduce outbox en este slice; un fallo Redis posterior al commit se registra y devuelve éxito de la mutación, riesgo residual documentado y cubierto por métricas/logs. Los tests de contrato verifican publicación en el camino normal.

### D-006: RBAC como dependencia FastAPI de allowlist exacta

Se añadirá `require_any_role(*roles: str)` en `app/dependencies/auth.py`, junto a `require_role` y `require_superadmin`, sin cambiar la semántica jerárquica usada por F1. El guard autoriza por pertenencia exacta y siempre permite `superadmin` cuando está incluido explícitamente; esto evita que una jerarquía permita escrituras a `analyst` por accidente.

```python
def require_any_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Permisos insuficientes")
        return user
    return _check
```

La matriz RBAC cubre los **cinco roles canónicos** persistidos en `chk_valid_role` (`viewer`, `analyst`, `ingestor`, `admin`, `superadmin`); cuatro de ellos tienen capacidad sobre Assets y `ingestor` está explícitamente denegado en los seis endpoints (sin capacidad de lectura, escritura ni export). Esto NO añade un rol nuevo: `ingestor` ya existe en F1/F2 y se mantiene intacto, simplemente no se incluye en ninguna `allowlist` del slice 1. La contabilización de casos del test parametrizado es 6 endpoints × 5 roles canónicos = 30 combinaciones en total (18 con permiso distribuido entre los cuatro roles con capacidad + 12 denegados: 6 de `ingestor` en los seis endpoints + 6 de `analyst`/`viewer` en POST/PATCH/DELETE).

| Operación | Roles declarados (`allowlist`) | Roles denegados |
| --- | --- | --- |
| POST, PATCH, DELETE | `admin`, `superadmin` | `analyst`, `viewer`, `ingestor` |
| GET list/by-id | `admin`, `analyst`, `viewer`, `superadmin` | `ingestor` |
| CSV export | `admin`, `analyst`, `viewer`, `superadmin` (alcance `own` para los tres primeros, `all` solo para `superadmin`; ver D-008 y D-012) | `ingestor` |

Cada endpoint declara `Depends(require_any_role(...))`; no hay checks RBAC dispersos dentro del service. El nombre de negocio `analista` del spec corresponde al literal F1 ya persistido `analyst`. En F2 el único rol con capacidad cross-tenant en assets es `superadmin`; `auditor_externo` se difiere a F3 y, por tanto, no aparece ni en `require_any_role`, ni en seeds, ni en checks de rol, ni en policies RLS en este slice.

### D-007: Tenant scoping en tres capas, tenant explícito y rutas diferenciadas para `superadmin`

La capa de datos conserva `tenant_id → tenants.id`, `uq_assets_id_tenant_id` y la RLS `rls_assets` creada en `migrations/versions/20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py:152`. La identidad compuesta `(id, tenant_id)` sigue siendo el target seguro para FKs de módulos hijos; la nueva unicidad no la sustituye.

La sesión procede de `DBWithTenantDep`, que usa `get_db_with_tenant()` y `set_tenant_context()` con `app.current_tenant` y `app.is_superadmin`, nombres reales verificados en `app/core/database.py:73-106`. Cada query recibe `tenant_id` como argumento del service y añade `Asset.tenant_id == tenant_id`; el service nunca lo deduce de la sesión.

```python
stmt = select(Asset).where(
    Asset.id == asset_id,
    Asset.tenant_id == tenant_id,
)
asset = (await db.execute(stmt)).scalar_one_or_none()
```

#### Rutas de scoping por tipo de usuario

El router aplica dos rutas diferenciadas según `current_user.is_superadmin`:

- **Usuarios tenant** (`admin`, `analyst`, `viewer`, `ingestor`): predicado explícito `Asset.tenant_id == current_user.tenant_id` en TODAS las queries (list y by-id). El body de POST DEBE coincidir con `current_user.tenant_id`; el router exige esa igualdad y rechaza con 422 si no coincide. Los accesos by-id fuera del tenant del usuario devuelven `404 Not Found` (no `403`), para no leak de existencia. `ingestor` nunca llega al service porque RBAC (`D-006`) lo bloquea antes con `403 Forbidden`.

- **`superadmin`**: predicado `Asset.tenant_id == ...` se OMITE tanto en listado como en by-id (queries seguras globales apoyadas en la policy RLS existente bajo `app.is_superadmin = 'true'`). POST DEBE recibir `tenant_id` explícito en el body como tenant objetivo (un superadmin NO tiene tenant implícito; el body es la única fuente de verdad); sin `tenant_id` o con `tenant_id` igual a NULL, el router responde 422. Para PATCH/DELETE by-id, la query se construye sin predicado de tenant y el `tenant_id` del asset se preserva tras la mutación (la mutación no cambia el tenant del recurso).

#### Tabla de scoping

| Endpoint | Usuario tenant | `superadmin` |
| --- | --- | --- |
| GET /assets (list) | predicado `Asset.tenant_id == current_user.tenant_id`; paginación normal | predicado de tenant omitido; paginación igual |
| GET /assets/{id} | predicado `tenant_id == current_user.tenant_id`; 404 si no existe o no pertenece | predicado de tenant omitido; 404 solo si el id no existe |
| POST /assets | `tenant_id` del body DEBE ser `current_user.tenant_id`; si no, 422 | `tenant_id` del body es el tenant objetivo (requerido); 422 si falta o es NULL |
| PATCH /assets/{id} | predicado de tenant; 404 si no pertenece | predicado de tenant omitido; tenant del asset sin cambios |
| DELETE /assets/{id} | predicado de tenant; 404 si no pertenece | predicado de tenant omitido; tenant del asset irrelevante |
| GET /assets?export=csv | alcance `own` (solo tenant del usuario) | alcance `all` (todos los tenants visibles por RLS) |

### D-008: Paginación offset/limit con total separado

El router declara `offset: Query(0, ge=0)` y `limit: Query(50, ge=1, le=200)`, por lo que FastAPI devuelve 422 antes del service para `limit=500`. El service ejecuta un count con el mismo predicado de alcance y una consulta ordenada por `created_at DESC, id DESC` para resultados deterministas.

```python
base = Asset.tenant_id == tenant_id
total_stmt = select(func.count()).select_from(Asset).where(base)
items_stmt = (
    select(Asset).where(base).order_by(Asset.created_at.desc(), Asset.id.desc())
    .offset(offset).limit(limit)
)
```

La respuesta será `{items, total, limit, offset}` mediante `AssetListResponse`, no una lista desnuda. En la vista cross-tenant (`superadmin`; `auditor_externo` queda diferido a F3) se omite únicamente el predicado `Asset.tenant_id == tenant_id` y se sustituye `base` por `True()` (o por la ausencia de predicado de tenant) en count e items; la policy RLS vigente `rls_assets` autoriza la lectura de todos los tenants bajo el contexto `app.is_superadmin = 'true'`. La forma final del query es idéntica para usuarios tenant y `superadmin` salvo por la presencia/ausencia del predicado de tenant: no hay rama especial en el service, solo el predicado se selecciona dinámicamente.

### D-009: Higiene de respuesta por whitelist

`AssetResponse` enumera exclusivamente los seis campos requeridos. La protección frente a fuga de atributos ORM NO viene de `extra="forbid"` — esa opción solo rechaza campos no declarados al construir el modelo desde un dict (request). El filtrado de atributos ORM se obtiene porque el schema declara únicamente los seis campos: al serializar (`model_dump()` o serialización FastAPI), Pydantic emite solo lo declarado y descarta cualquier otro atributo del ORM. `ConfigDict(from_attributes=True, extra="forbid", populate_by_name=True)` se usa entonces con dos fines diferenciados: `from_attributes` permite construir el response desde la instancia ORM, `extra="forbid"` rechaza campos inesperados en la construcción y `populate_by_name` permite usar alias cuando aplique. El router siempre materializa el response schema antes de devolverlo.

```python
class AssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")
    id: UUID
    type: AssetType
    value: str
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime
```

Se añadirá una propiedad o mapping explícito desde `asset_type` a `type`; no se serializa `__dict__`. `created_at` y `updated_at` son explícitamente públicos por contrato del slice 1 (no son timestamps internos): se exponen en cada response para soporte de auditoría y ordenamiento por cliente. Quedan fuera `status`, `asset_metadata`, `created_by_user_id`, `raw_input` y cualquier campo interno o no documentado en el spec. CSV usa exactamente la misma whitelist y un orden fijo de columnas.

### D-010: Split de tests y fixtures multi-tenant existentes

`tests/unit/test_assets.py` cubrirá validadores, normalización, unicidad, queries con tenant, paginación y eventos mockeados. `tests/api/test_assets.py` cubrirá los cinco endpoints, export CSV, códigos 404/409/422, response hygiene y la matriz parametrizada de 6 operaciones × 5 roles canónicos = **30 combinaciones** (18 con capacidad distribuida entre `admin`/`analyst`/`viewer`/`superadmin` y 12 denegados: 6 de `ingestor` en los seis endpoints + 6 de `analyst`/`viewer` en POST/PATCH/DELETE), consistente con el spec.

#### Cliente HTTP y contexto RLS

Se reutiliza `seed_data` de `tests/conftest.py:178`, que devuelve las claves reales `tenant_a`, `tenant_b`, `superadmin`, `admin_a`, `analyst_a`, `viewer_a` y `admin_b`. También se usan `admin_a_headers`, `analyst_a_headers`, `viewer_a_headers`, `admin_b_headers` y el `client` basado en `httpx.AsyncClient`; el proyecto no usa `fastapi.testclient.TestClient` síncrono.

**Aclaración crítica sobre fixtures**: `httpx.AsyncClient` con `ASGITransport(app=app)` actúa solo como transport/cliente HTTP contra la app ASGI; por sí mismo no establece contexto RLS ni tenant. El override de `get_db` definido en `tests/conftest.py` (que produce un `yield db_session`) tampoco invoca `set_tenant_context()`: ese override solo reemplaza la sesión de base de datos, no el contexto Postgres. El contexto RLS solo se materializa cuando se ejecuta la dependencia tenant-aware `get_db_with_tenant()` (`app/dependencies/db_deps.py`), la cual invoca `set_tenant_context(db_session, current_user.tenant_id, current_user.is_superadmin)` con el `current_user` resuelto por `get_current_user`. Por tanto, los tests API de aislamiento multi-tenant DEBEN:

- (a) sobrescribir explícitamente `get_db_with_tenant` con un override que también invoque `set_tenant_context(db_session, current_user.tenant_id, current_user.is_superadmin)` para el rol y tenant del test (análogo al patrón de `tests/modules/auth/test_refresh_token_race.py`); o bien
- (b) invocar `await set_tenant_context(db_session, tenant_id, is_superadmin)` directamente sobre la sesión del test antes de la request, replicando el contrato de `get_db_with_tenant`.

NO DEBE asumirse que el override plano de `get_db` aplica automáticamente RLS: ese override solo reemplaza la sesión de base de datos, no el contexto Postgres.

#### Casos cubiertos

Los casos cross-tenant crean assets para A y B, verifican 404 en GET/PATCH/DELETE by-id desde admin de tenant B contra assets de A, aislamiento del listado normal para admin/analyst/viewer y exposición global solo para `superadmin` en el listado y en el export. Los casos de `ingestor` verifican `403 Forbidden` para los seis endpoints sin importar el tenant del recurso. No se siembra ni se autoriza a `auditor_externo` en este slice (diferido a F3).

### D-011: Roles activos en F2 y diferimiento del auditor

Este slice NO introduce `auditor_externo`. Los literales canónicos de rol activos en F2 son exactamente: `viewer`, `analyst`, `ingestor`, `admin`, `superadmin` (estos dos últimos según `app/modules/users/models.py:30`). `chk_valid_role` y `chk_user_has_tenant` NO se modifican en este slice: el auditor, si se añade, se modela en su propio slice F3 con su propia revisión Alembic.

En F2 el único rol con capacidad cross-tenant sobre assets es `superadmin`. Su lectura global sigue apoyándose en la sesión con `app.current_tenant` y la policy RLS existente; no se crea en este slice una policy `app.cross_tenant_read` ni un bypass de RLS adicional, porque no es necesario para limitar el alcance a `superadmin`. Si más adelante F3 requiere una policy SELECT-only dedicada para `auditor_externo`, se añadirá en esa fase con su propia migración.

`analyst` se mantiene como literal canónico compatible con F1; sigue representando el rol funcional `analista` de la matriz del producto. La sustitución por `analista` ocurriría solo si F3 decide renombrarlo, y debe documentarse de forma explícita.

### D-012: Contrato CRUD, errores y export CSV

Las rutas se implementarán en `app/modules/assets/router.py` y se registrarán en `app/main.py` con prefijo `/api/v1`. POST devuelve 201 y `AssetResponse`; GET by-id y PATCH devuelven 200; DELETE devuelve 204 sin body; duplicados capturados desde `IntegrityError` de `uq_assets_tenant_type_value` devuelven 409.

`GET /assets?export=csv` comparte ruta con el listado mediante `export: Literal["csv"] | None`. Con `csv`, devuelve `StreamingResponse(media_type="text/csv")` y cabecera `Content-Disposition`; sin `csv`, devuelve `AssetListResponse`. La query de export no pagina y aplica alcance `own` (solo el tenant del usuario) para `admin`, `analyst` y `viewer`, y alcance `all` (todos los tenants visibles por la policy RLS) únicamente para `superadmin`. `ingestor` recibe `403 Forbidden` antes de llegar a la rama de export (RBAC en `D-006`); `auditor_externo` queda fuera de este slice y, por tanto, no participa en el export.

Los cambios de implementación quedan delimitados así:

| Archivo | Acción prevista |
| --- | --- |
| `app/modules/assets/models.py` | Renombrar atributos/constraints y corregir `__repr__` |
| `app/modules/assets/schemas.py` | Crear requests discriminadas y responses whitelist |
| `app/modules/assets/service.py` | Crear CRUD, validación, paginación y publicación |
| `app/modules/assets/router.py` | Crear endpoints, RBAC, scoping y CSV |
| `app/event_schemas.py` | Añadir los tres eventos tipados de assets |
| `app/event_bus/bus.py` | Añadir override opcional de stream |
| `app/dependencies/auth.py` | Añadir guard de allowlist |
| `app/modules/users/models.py` y `schemas.py` | Sin cambios en este slice (no se introduce `auditor_externo`) |
| `app/core/security.py` | Sin cambios (los cinco literales canónicos siguen activos) |
| `app/main.py` | Registrar el router de assets |
| `migrations/versions/<revision>_align_assets_model_for_slice_1.py` | Aplicar solo DDL de assets (sin tocar checks de rol ni añadir policies cross-tenant) |
| `tests/unit/test_assets.py`, `tests/api/test_assets.py` | Cubrir service, API, RBAC y aislamiento sobre los 5 roles canónicos (los cuatro con capacidad sobre Assets más `ingestor` denegado en los seis endpoints) |

Flujo concreto:

```text
JWT → get_current_user → require_any_role → DB/RLS context
                                      ↓
request schema → router tenant policy → Asset service → PostgreSQL commit
                                                   ↓
                                    EventBus → stream asset.events
```

## Migration Plan

`uv run alembic revision -m "align assets model for slice 1"`

La nueva revisión apuntará al head actual y no modificará migraciones ya aplicadas. Antes de alterar DDL, `upgrade()` ejecutará la precondición de unicidad; la consulta se materializa con `op.get_bind()` y `result.fetchall()`, y si la lista NO está vacía se lanza `RuntimeError(...)` con un mensaje accionable que indique explícitamente que hay duplicados preexistentes y cómo resolverlos. Esto aborta la revisión antes de cualquier DDL, en lugar de dejar que `ADD CONSTRAINT` falle opacamente. El código será:

```python
conn = op.get_bind()
dup_rows = conn.execute(
    sa.text(
        "SELECT tenant_id, asset_type, name, count(*) AS n "
        "FROM assets GROUP BY tenant_id, asset_type, name HAVING count(*) > 1"
    )
).fetchall()
if dup_rows:
    raise RuntimeError(
        "Cannot add uq_assets_tenant_type_value: existing duplicates "
        f"({len(dup_rows)} groups). Resolve before running upgrade."
    )
```

A continuación, `upgrade()` eliminará `chk_assets_asset_type`, renombrará `name` a `value` con `op.alter_column`, eliminará `hostname`, actualizará filas cuyo `asset_type='host'` a `hostname`, recreará el check con exactamente `hostname`, `domain`, `ip`, `web_app`, `subnet` y `cloud_resource`, y creará `uq_assets_tenant_type_value`. Mantendrá sin cambios `chk_assets_status`, `uq_assets_id_tenant_id`, índices, trigger, grants y policy tenant existentes.

Esta revisión NO toca `chk_valid_role`, `chk_user_has_tenant`, ni añade policies RLS adicionales: `auditor_externo` se difiere a F3 y los cinco literales canónicos de F1 siguen activos sin cambios.

`downgrade()` abortará de forma explícita antes del primer DDL si la BD contiene filas con `asset_type IN ('subnet', 'cloud_resource')`, ya que estos literales se perderían al restaurar el check de cuatro valores. El código será:

```python
conn = op.get_bind()
new_types = conn.execute(
    sa.text(
        "SELECT count(*) FROM assets WHERE asset_type IN ('subnet', 'cloud_resource')"
    )
).scalar_one()
if new_types:
    raise RuntimeError(
        "Cannot downgrade: rows with asset_type 'subnet' or 'cloud_resource' "
        f"exist ({new_types}). Migrate or delete before downgrade."
    )
```

Sólo si la cuenta es cero seguirá el `downgrade()`: eliminará `uq_assets_tenant_type_value`, eliminará el check de seis tipos, mapeará `hostname` a `host`, recreará la columna nullable `hostname`, renombrará `value` a `name` y restaurará `chk_assets_asset_type` con `host`, `domain`, `ip`, `web_app`. El contenido histórico de la columna eliminada no puede reconstruirse y vuelve como `NULL`.

La verificación ejecutará upgrade sobre una BD con filas, comprobará preservación del count y valores, ejecutará `uv run alembic check`, y probará downgrade/upgrade (incluido el caso de filas con `subnet`/`cloud_resource` para confirmar que el `RuntimeError` aborta correctamente). Antes del merge se ejecutarán los dos archivos del slice y la suite completa para detectar referencias antiguas.

## Riesgos Específicos del Slice

- El rename `name` → `value` puede romper callers existentes. Mitigación obligatoria: `grep -rn "\.name" app/modules/assets/ tests/` antes del merge y actualización de cada referencia legítima.
- El unique `(tenant_id, asset_type, value)` puede fallar con datos duplicados. La precondición se materializa con `op.get_bind().execute(...).fetchall()` y, si la lista no está vacía, lanza `RuntimeError(...)` con mensaje accionable. Esto aborta la revisión antes del DDL en lugar de fallar opacamente al añadir el constraint.
- El cambio literal `host` → `hostname` puede dejar comparaciones antiguas. Ejecutar `grep -rnE "['\"]host['\"]" app/ tests/` y distinguir roles/hosts ajenos al asset type.
- El downgrade puede perder datos si la BD ya contiene `subnet` o `cloud_resource`. La precondición `WHERE asset_type IN ('subnet', 'cloud_resource')` cuenta filas y, si es distinta de cero, aborta con `RuntimeError(...)` antes de restaurar el check de cuatro valores.
- Composite identity y RLS son defensas complementarias. La policy verificada usa `current_setting('app.current_tenant', TRUE)`, no `app.tenant_id`; tests deben confirmar que el filtro router y RLS coinciden.
- Commit seguido de Redis no es atómico: una caída entre ambos deja la mutación sin evento. Se acepta en slice 1 sin outbox, con log/métrica; una garantía de entrega requerirá un slice de outbox posterior.
- `auditor_externo` se difiere a F3. Cualquier intento de meterlo en este slice reintroduce el riesgo de mezclar capacidad cross-tenant con permisos de escritura o de gestión de tenants. Mantenerlo fuera de F2 preserva `is_superadmin` como único disparador de cross-tenant sobre assets.
- La normalización puede convertir dos inputs distintos en el mismo valor canónico y provocar 409; esto es deseado, pero debe documentarse en tests (`2001:0db8::1` frente a `2001:db8::1`).

## Out of Scope (this slice)

- No se ejecutan scans ni se implementan schedules o triggers de scanning.
- No hay detección, deduplicación ni lifecycle de vulnerabilidades.
- No se implementan las nueve funciones de enriquecimiento LLM; corresponden al slice 8.
- No se generan PDFs ni reportes de ningún tipo.
- No se implementan consumidores de eventos; este slice publica solamente.
- No se construye dashboard ni métricas agregadas de producto.
- No se introduce Celery, Celery Beat, workers ni tareas background.
- No se implementa Nmap, LangGraph, webhooks ni frontend.
- Los consumidores y capacidades anteriores pertenecen a los slices 2-9 del cambio.
