# Tasks: Slice 1 — Assets

> Plan ejecutable para el primer módulo CRUD vertical de F2. Alineado con
> `design.md` (D-001..D-012) y `specs/f2-assets/spec.md`. Auditoría final
> de approval ya cerrada en sesión 2026-09-04. Implementación se ejecuta
> sobre la rama `sdd/prd-v2-vertical-f2` con TDD estricto.

## Reglas de oro (non-negotiable)

1. **TDD estricto**: cada requisito del spec tiene un test rojo ANTES de
   la implementación. Triangulación solo cuando hace falta (p. ej. misma
   lógica, dos entradas distintas).
2. **RLS override en tests**: los tests API multi-tenant deben sobrescribir
   `get_db_with_tenant` invocando `set_tenant_context(db_session, tenant_id,
   is_superadmin)` — el override plano de `get_db` NO aplica RLS (ver
   `design.md` D-010 aclaración crítica).
3. **Migration primero**: T1 crea la revisión Alembic antes que cualquier
   modelo, schema o servicio que dependa del shape nuevo (`value`, six
   asset types, unique constraint).
4. **Outbox NO en este slice**: la mutación commit + Redis no son atómicos;
   un fallo Redis posterior al commit registra log/métrica y devuelve
   éxito. Outbox pertenece a un slice posterior.
5. **`auditor_externo` no existe en F2**: cualquier tentación de meterlo
   reintroduce el riesgo de mezclar capacidad cross-tenant con permisos
   de escritura. Difiere a F3.
6. **No commits durante implementación** sin gate humano verde. La sesión
   de implementación termina con un verify limpio y un gate al usuario.

---

## Fase T1 — Migración Alembic

**Referencia**: `design.md` D-001 y `Migration Plan`; `spec.md` Requisitos
"Migration del modelo Asset a 6 tipos + campo `value` + unique".

### T1.1 — Crear revisión nueva sobre el head actual

- Comando: `uv run alembic revision -m "align assets model for slice 1"`.
- Archivo destino: `migrations/versions/<rev>_align_assets_model_for_slice_1.py`.
- `down_revision` resuelve a la cabeza única actual (verificada con
  `uv run alembic heads` antes de crear la revisión; abortar y resolver
  si hay múltiples cabezas).
- **No** editar la revisión histórica
  `20260625_1400_f2_assets_scans_tenant_8f2c1a4b9d7e.py`.

### T1.2 — `upgrade()` con precondición de unicidad

Pseudocódigo objetivo (extracto de `design.md` D-001 / Migration Plan):

```python
def upgrade() -> None:
    conn = op.get_bind()
    dup_rows = conn.execute(sa.text(
        "SELECT tenant_id, asset_type, name, count(*) AS n "
        "FROM assets GROUP BY tenant_id, asset_type, name HAVING count(*) > 1"
    )).fetchall()
    if dup_rows:
        raise RuntimeError(
            "Cannot add uq_assets_tenant_type_value: existing duplicates "
            f"({len(dup_rows)} groups). Resolve before running upgrade."
        )

    op.drop_constraint("chk_assets_asset_type", "assets", type_="check")
    op.alter_column("assets", "name", new_column_name="value")
    op.drop_column("assets", "hostname")
    op.execute(
        "UPDATE assets SET asset_type='hostname' WHERE asset_type='host'"
    )
    op.create_check_constraint(
        "chk_assets_asset_type", "assets",
        "asset_type IN ('hostname','domain','ip','web_app','subnet','cloud_resource')",
    )
    op.create_unique_constraint(
        "uq_assets_tenant_type_value", "assets",
        ["tenant_id", "asset_type", "value"],
    )
```text

Mantener sin cambios: `chk_assets_status`, `uq_assets_id_tenant_id`,
índices, triggers, grants y policy tenant existentes. NO tocar
`chk_valid_role`, `chk_user_has_tenant`, ni añadir policies RLS
adicionales.

### T1.3 — `downgrade()` con precondición de tipos nuevos

Regla "todo o nada": o completa el DDL o aborta antes del primero
con `RuntimeError`. Sin ejecuciones parciales.

```python
def downgrade() -> None:
    conn = op.get_bind()
    new_types = conn.execute(sa.text(
        "SELECT count(*) FROM assets WHERE asset_type IN ('subnet','cloud_resource')"
    )).scalar_one()
    if new_types:
        raise RuntimeError(
            "Cannot downgrade: rows with asset_type 'subnet' or 'cloud_resource' "
            f"exist ({new_types}). Migrate or delete before downgrade."
        )
    op.drop_constraint("uq_assets_tenant_type_value", "assets", type_="unique")
    op.drop_constraint("chk_assets_asset_type", "assets", type_="check")
    op.execute("UPDATE assets SET asset_type='host' WHERE asset_type='hostname'")
    op.add_column("assets", sa.Column("hostname", sa.String(255), nullable=True))
    op.alter_column("assets", "value", new_column_name="name")
    op.create_check_constraint(
        "chk_assets_asset_type", "assets",
        "asset_type IN ('host','domain','ip','web_app')",
    )
```text

El contenido histórico de la columna `hostname` eliminada vuelve como
`NULL` — pérdida deliberada y documentada (ver `design.md` Riesgos).

### T1.4 — Tests de la migración

- **Roundtrip**: aplicar upgrade sobre BD con N filas; verificar que N
  filas siguen presentes, `value` poblado, `chk_assets_asset_type` con
  seis valores, `uq_assets_tenant_type_value` presente.
- **Drift**: tras aplicar la migración, `inspect(Asset)` contra el
  modelo nuevo y `uv run alembic check` no debe reportar diferencias.
- **Upgrade abort**: precondición de duplicados. Crear tabla con dos
  filas `(tenant_id=A, asset_type=ip, name=1.2.3.4)` antes de upgrade;
  el `RuntimeError` debe abortar ANTES del DDL.
- **Downgrade abort**: insertar `(tenant_id=A, asset_type=subnet,
  value=10.0.0.0/24)` y ejecutar `alembic downgrade -1`; el
  `RuntimeError` debe abortar y dejar el schema en su estado
  post-upgrade (`chk_assets_asset_type` de seis tipos y
  `uq_assets_tenant_type_value` presentes).
- **Downgrade éxito**: con BD sin filas `subnet`/`cloud_resource`,
  `downgrade -1` restaura `host`, `domain`, `ip`, `web_app`, columna
  `hostname` nullable presente y `value` → `name`.

### T1.5 — Verify

- `uv run alembic upgrade head` sobre BD limpia de tests.
- `uv run alembic check` (debe pasar sin drift).
- Smoke: insertar fila `(tenant_id=A, asset_type=hostname,
  value=app.example.com)` y consultar `uq_assets_tenant_type_value`.

---

## Fase T2 — Modelo `Asset`

**Referencia**: `app/modules/assets/models.py` actual; `design.md` D-009.

### T2.1 — Renombrar atributos y constraint

- `name: Mapped[str]` → `value: Mapped[str]` (mantener `String(255)`,
  `nullable=False`).
- Eliminar la columna `hostname`.
- Sustituir `__table_args__` `chk_assets_asset_type` por la versión
  extendida con seis valores (alineado con la migración T1).
- Mantener `chk_assets_status`, `uq_assets_id_tenant_id`, los índices
  existentes y los `Mapped` con sus defaults.

### T2.2 — `__repr__` y semántica

- Reemplazar `f"<Asset id={self.id} name={self.name!r}>"` por
  `f"<Asset id={self.id} type={self.asset_type!r} value={self.value!r}>"`.
- No añadir métodos nuevos en este slice (todo lo no listado en el spec
  queda fuera).

### T2.3 — Grep preventivo post-cambio

- `grep -rn "\.name" app/modules/assets/ tests/` — actualizar
  referencias legítimas a `\.value`.
- `grep -rnE "['\"]host['\"]" app/ tests/` — distinguir roles/hosts
  ajenos al asset type; las únicas apariciones legítimas de `'host'`
  como literal de asset_type deben migrar a `'hostname'`.

---

## Fase T3 — Schemas Pydantic

**Referencia**: `design.md` D-003, D-009; `spec.md` Requirement
"Respuestas no leakean campos sensibles".

### T3.1 — Discriminated union para POST

Archivo: `app/modules/assets/schemas.py`. Estructura objetivo:

```python
class AssetCreateBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenant_id: UUID
    value: str = Field(min_length=1, max_length=255)

class IpAssetCreate(AssetCreateBase):
    type: Literal["ip"]

# Idem para Domain, Hostname, WebApp, Subnet, CloudResource
AssetCreateRequest = Annotated[
    Union[IpAssetCreate, DomainAssetCreate, HostnameAssetCreate,
          WebAppAssetCreate, SubnetAssetCreate, CloudResourceAssetCreate],
    Field(discriminator="type"),
]
```text

Pydantic cubre shape, discriminator, longitud y campos desconocidos
(`extra="forbid"`). La validación semántica por tipo vive en el
service (T4.2).

### T3.2 — Schema de PATCH

- `AssetUpdate(type: AssetType | None, value: str | None)` con
  `extra="forbid"`. El service combina los campos enviados con el
  estado persistido y valida el par resultante; no se usa unión
  ambigua aquí.

### T3.3 — Response whitelist

- `AssetResponse(BaseModel)` con exactamente seis campos: `id`,
  `type`, `value`, `tenant_id`, `created_at`, `updated_at`.
- `model_config = ConfigDict(from_attributes=True, extra="forbid",
  populate_by_name=True)`.
- Mapping explícito desde `Asset.asset_type` a `AssetResponse.type`
  (no se serializa `__dict__`).
- Excluidos: `status`, `asset_metadata`, `created_by_user_id`,
  `raw_input`. `created_at`/`updated_at` son públicos por contrato
  del slice 1 (ver `design.md` D-009).

### T3.4 — List response

- `AssetListResponse(items: list[AssetResponse], total: int,
  limit: int, offset: int)`.

---

## Fase T4 — Service `AssetService`

**Referencia**: `design.md` D-002, D-003, D-004, D-005, D-007, D-008.

### T4.1 — Esqueleto asíncrono

Archivo: `app/modules/assets/service.py`. Funciones `async def` que
reciben `AsyncSession` y `EventBus` explícitamente (D-002). Patrón de
funciones de módulo, sin clase con estado. El servicio nunca deduce
`tenant_id` de la sesión; lo recibe como argumento.

Firma objetivo:

```python
async def create_asset(
    data: AssetCreateRequest, tenant_id: UUID,
    db: AsyncSession, event_bus: EventBus,
) -> Asset: ...

async def get_asset(
    asset_id: UUID, tenant_id: UUID | None,
    db: AsyncSession,
) -> Asset | None: ...

async def list_assets(
    tenant_id: UUID | None,
    db: AsyncSession,
    *, limit: int, offset: int,
) -> tuple[Sequence[Asset], int]: ...

async def update_asset(
    asset_id: UUID, tenant_id: UUID | None, data: AssetUpdate,
    db: AsyncSession, event_bus: EventBus,
) -> Asset | None: ...

async def delete_asset(
    asset_id: UUID, tenant_id: UUID | None,
    db: AsyncSession, event_bus: EventBus,
) -> bool: ...
```text

### T4.2 — Validación semántica por tipo

Helper privado síncrono `_validate_asset_value(asset_type, value) -> str`
que aplica la tabla de `design.md` D-004:

| Tipo | Validador | Normalización |
| --- | --- | --- |
| `ip` | `ipaddress.ip_address` | comprimido canónico IPv4/IPv6 |
| `domain` | regex FQDN por labels | lowercase sin punto final |
| `hostname` | regex RFC 1123 | lowercase |
| `web_app` | `pydantic.HttpUrl` | string URL normalizada; `http`/`https` |
| `subnet` | `ipaddress.ip_network(strict=False)` | network address CIDR |
| `cloud_resource` | regex AWS ARN anclada | conserva case del resource |

Mensajes exactos exigidos: IP inválida → `value must be a valid IPv4 or
IPv6 address`; FQDN inválido → `value must be a valid FQDN`; CIDR
inválido → `value must be a valid CIDR`. ARN acepta como mínimo
`arn:partition:service:region:account-id:resource`, incluido
`arn:aws:s3:::my-bucket`.

El helper se invoca en POST y sobre el estado efectivo de PATCH.
Devuelve el valor normalizado o levanta `ValueError` con el mensaje
esperado; el router lo traduce a 422.

### T4.3 — Captura de IntegrityError → 409

En `create_asset` y `update_asset`, capturar `IntegrityError` cuya
constraint violada sea `uq_assets_tenant_type_value` y relanzar como
excepción de dominio (`AssetDuplicateError`) con el código 409 ya
decidido en el router. Ningún otro `IntegrityError` se traduce a 409.

### T4.4 — Publicación de eventos

Tras `await db.commit()` exitoso, construir y publicar el evento en
`asset.events` con `event_bus.publish(event, stream="asset.events")`
(ver T6 y T7). El snapshot del evento se captura tras `flush` y se
publica únicamente si el commit no lanza.

### T4.5 — Tenant scoping interno

- `tenant_id is not None`: el service añade `Asset.tenant_id ==
  tenant_id` a cada query. Para PATCH/DELETE, devolver `None` cuando
  el asset no pertenece al tenant; el router traduce `None` a 404
  (D-007).
- `tenant_id is None`: predicado de tenant omitido (ruta superadmin).

### T4.6 — Paginación

Count con el mismo predicado de alcance + items ordenados por
`created_at DESC, id DESC` (D-008). No paginar `list_assets` cuando se
sirve CSV (esa rama vive en el router y debe reutilizar el service sin
paginar; ver T8.5).

---

## Fase T5 — Guard `require_any_role`

**Referencia**: `design.md` D-006; `app/dependencies/auth.py`.

### T5.1 — Nueva dependencia

Añadir a `app/dependencies/auth.py`:

```python
def require_any_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Permisos insuficientes")
        return user
    return _check
```text

Sin cambiar la semántica de `require_role` ni `require_superadmin`.
El guard autoriza por pertenencia exacta y siempre permite
`superadmin` cuando está explícitamente en la allowlist. NO introduce
jerarquía implícita: si `analyst` no está en la allowlist del endpoint,
no entra, ni siquiera por jerarquía.

### T5.2 — Export

Reexportar en `app/dependencies/__init__.py` junto a `require_role`,
`require_superadmin`, `get_current_user`, etc.

---

## Fase T6 — Eventos tipados

**Referencia**: `design.md` D-005; `app/event_schemas.py`.

### T6.1 — Tres eventos nuevos

Añadir a `app/event_schemas.py`:

```python
class AssetCreatedEvent(BaseEvent):
    event_type: Literal["asset.created"] = "asset.created"
    asset_id: UUID
    type: AssetType
    value: str
    created_at: datetime

class AssetUpdatedEvent(BaseEvent):
    event_type: Literal["asset.updated"] = "asset.updated"
    asset_id: UUID
    changed_fields: list[str]  # ["type", "value"] en orden estable

class AssetDeletedEvent(BaseEvent):
    event_type: Literal["asset.deleted"] = "asset.deleted"
    asset_id: UUID
```text

`changed_fields` se calcula como la lista ordenada de campos públicos
realmente cambiados (D-005). El `tenant_id` ya viene en el envelope
`BaseEvent` común.

### T6.2 — Smoke test de schema

Test unitario que cada evento serializa a JSON válido y conserva los
campos esperados (sin acoplar al bus todavía — solo al modelo).

---

## Fase T7 — `EventBus.publish` con override de stream

**Referencia**: `design.md` D-005; `app/event_bus/bus.py`.

### T7.1 — Override opcional

Modificar la firma de `EventBus.publish(event, stream=None)` (o el
parámetro explícito equivalente) aceptando un override de stream. Por
defecto conserva el comportamiento F1. El módulo de assets usará
`stream="asset.events"` (D-005).

### T7.2 — Test unitario

Mockear Redis client y verificar que `publish(event,
stream="asset.events")` escribe en el stream correcto y serializa el
payload declarado. No se introduce outbox en este slice.

---

## Fase T8 — Router `Asset`

**Referencia**: `design.md` D-007, D-008, D-012.

### T8.1 — Esqueleto y registro

- `app/modules/assets/router.py` con `APIRouter(prefix="/assets",
  tags=["assets"])`.
- Registrar en `app/main.py` con prefijo `/api/v1` (análogo a
  `app/modules/tenants/router.py:19` y registro en `app/main.py:261-263`).

### T8.2 — POST `/assets`

- `Depends(require_any_role("admin", "superadmin"))` — `analyst`,
  `viewer` e `ingestor` reciben 403 (RBAC D-006).
- Body: `AssetCreateRequest` (discriminated union).
- Reglas de tenant:
  - Usuarios tenant (no `superadmin`): `tenant_id` del body DEBE ser
    igual a `current_user.tenant_id`. Si no, 422 `tenant_id mismatch`.
  - `superadmin`: `tenant_id` del body es el tenant objetivo. Si falta
    o es `None`, 422 `tenant_id is required`. Validar que el tenant
    existe antes de crear.
- Llama `service.create_asset(...)`. Devuelve 201 con `AssetResponse`.
- `IntegrityError`/`AssetDuplicateError` → 409.
- ValueError del validador → 422 con el mensaje exacto del D-004.

### T8.3 — GET `/assets` (list + export CSV)

- `Depends(require_any_role("admin", "analyst", "viewer",
  "superadmin"))` — solo `ingestor` recibe 403.
- Parámetros query: `offset: int = Query(0, ge=0)`,
  `limit: int = Query(50, ge=1, le=200)`,
  `export: Literal["csv"] | None = None`.
- Paginación: `service.list_assets(...)` → `AssetListResponse`.
- Si `export == "csv"`:
  - Construir CSV desde la query SIN paginar.
  - Alcance:
    - Usuarios tenant: solo su tenant (`Asset.tenant_id ==
      current_user.tenant_id`).
    - `superadmin`: todos los tenants (la policy RLS existente con
      `app.is_superadmin = 'true'` autoriza la lectura global — ver
      D-007 y D-012).
  - Devolver `StreamingResponse(media_type="text/csv",
    headers={"Content-Disposition":
    "attachment; filename=assets.csv"})`.
- Whitelist de columnas (mismo orden en el CSV que en response JSON):
  `id, type, value, tenant_id, created_at, updated_at`.

### T8.4 — GET `/assets/{id}`

- Mismo `require_any_role` que el listado.
- Usuarios tenant: predicado `Asset.tenant_id ==
  current_user.tenant_id`; `None` → 404 (no 403, no leak de
  existencia).
- `superadmin`: predicado de tenant omitido; `None` → 404 solo si el
  id no existe en la BD.
- Devuelve 200 con `AssetResponse`.

### T8.5 — PATCH `/assets/{id}`

- `Depends(require_any_role("admin", "superadmin"))`.
- Body: `AssetUpdate`.
- Predicados de tenant análogos a GET by-id.
- Validar valor efectivo tras combinar patch con estado persistido
  (T4.2 sobre `(effective_type, effective_value)`).
- 200 con `AssetResponse`; 404 si no pertenece; 409 si genera
  duplicado; 422 si valor semánticamente inválido.
- Publica `asset.updated` con `changed_fields = ["type", "value"]`
  (los que realmente cambiaron).

### T8.6 — DELETE `/assets/{id}`

- `Depends(require_any_role("admin", "superadmin"))`.
- Predicados análogos. 204 sin body; 404 si no pertenece.
- Publica `asset.deleted` tras commit.

### T8.7 — Aislamiento cross-tenant + superadmin

Implementar las dos rutas diferenciadas según
`current_user.is_superadmin` (no mediante una rama gigante). El patrón
recomendado es una función helper interna
`_scope_query(stmt, current_user) -> Select` que añade u omite el
predicado de tenant. La policy RLS existente ya autoriza a
`superadmin` con `app.is_superadmin = 'true'`; no se crea ninguna
policy adicional en este slice (D-011).

---

## Fase T9 — Registro en `main.py`

**Referencia**: `app/main.py:261-263` y diseño general de routers F1.

- Importar `app.modules.assets.router as assets_router`.
- `app.include_router(assets_router.router, prefix="/api/v1")` junto a
  los routers F1 ya registrados. Sin middleware nuevo, sin tags
  personalizados más allá de los declarados en el router.

---

## Fase T10 — Tests unitarios

**Referencia**: `design.md` D-010; `tests/unit/test_assets.py` (nuevo).

### T10.1 — Validadores `_validate_asset_value`

Tabla de casos mínimos por tipo:

- `ip`: acepta v4 y v6, rechaza basura y prefijo fuera de rango;
  verifica mensaje exacto (`"value must be a valid IPv4 or IPv6
  address"`).
- `domain`: acepta FQDN, rechaza label inválido (`-bad-.com`),
  verifica normalización a lowercase y sin punto final.
- `hostname`: acepta `app.example.com`, rechaza con espacios, verifica
  normalización.
- `web_app`: acepta `https://app.example.com/path?q=1`, rechaza
  `ftp://...`.
- `subnet`: acepta `192.168.0.0/24`, rechaza `/40` y `/abc`, verifica
  network address canónica.
- `cloud_resource`: acepta `arn:aws:s3:::my-bucket`, rechaza ARN sin
  resource.

### T10.2 — Modelos y unicidad

- Test de migración (T1.4) vive aquí también.
- Test de unicidad a nivel SQLAlchemy: intentar dos `INSERT` con misma
  `(tenant_id, asset_type, value)` produce `IntegrityError` cuya
  constraint name es `uq_assets_tenant_type_value`.

### T10.3 — Service puro

- `create_asset` con mock de `AsyncSession` y `EventBus`: verifica que
  se llama `flush`, `commit`, `publish(stream="asset.events")` en
  orden.
- `list_assets` con mock: count y items devueltos en el orden
  especificado.
- `update_asset`: `changed_fields` se calcula correctamente.

### T10.4 — Eventos

- T6.2 cubre el smoke de schema.
- Verificar que `publish(event, stream="asset.events")` se llama con
  los tres tipos de evento.

---

## Fase T11 — Tests API

**Referencia**: `design.md` D-010; `tests/api/test_assets.py` (nuevo);
`spec.md` Requirements y Scenarios completos.

### T11.1 — Override de `get_db_with_tenant` con RLS

CRÍTICO: el `client` fixture actual en `tests/conftest.py` solo
reemplaza la sesión de DB; NO invoca `set_tenant_context`. Esto
rompe los tests de aislamiento multi-tenant. Decisión:

- Crear un nuevo fixture `tenant_client` (función-scoped) que se
  apoye en `seed_data` y:
  1. Cree un `app = create_app()`.
  2. Sobrescriba `get_db` con `override_get_db` actual (yield
     sesión).
  3. Sobrescriba `get_db_with_tenant` con un override que capture
     `current_user` via `get_current_user` e invoque
     `await set_tenant_context(db_session, current_user.tenant_id,
     current_user.is_superadmin)` antes de hacer `yield db_session`.
  4. Sobrescriba `get_redis` con `FakeRedis` Lua-capaz.
  5. Abra `AsyncClient(transport=ASGITransport(app=app),
     base_url="http://test")` y `yield ac`.
- Alternativa más simple para tests específicos: el test invoca
  `await set_tenant_context(db_session, tenant_id, is_superadmin)`
  directamente antes de la request (válido y documentado en D-010).
- Decisión final: priorizar el fixture `tenant_client` para los
  tests de slice 1; mantener el `client` legacy intacto para no
  romper otros tests F1.

### T11.2 — Matriz RBAC (30 combinaciones)

Test parametrizado sobre los 6 endpoints × 5 roles canónicos:
`viewer`, `analyst`, `ingestor`, `admin`, `superadmin`. Total **30
combinaciones** (18 con permiso distribuido entre
`admin`/`analyst`/`viewer`/`superadmin` y 12 denegados: 6 de
`ingestor` en los seis endpoints + 6 de `analyst`/`viewer` en
POST/PATCH/DELETE). Cada combinación ejecuta la request y verifica
el código esperado:

| Endpoint | admin | analyst | viewer | superadmin | ingestor |
| --- | --- | --- | --- | --- | --- |
| POST | 201 | 403 | 403 | 201 (target explícito) | 403 |
| GET list | 200 | 200 | 200 | 200 (cross-tenant) | 403 |
| GET by-id (de su tenant) | 200 | 200 | 200 | 200 | 403 |
| GET by-id (cross-tenant) | 404 | 404 | 404 | 200 | 403 |
| PATCH | 200 | 403 | 403 | 200 | 403 |
| DELETE | 204 | 403 | 403 | 204 | 403 |
| GET ?export=csv | 200 (own) | 200 (own) | 200 (own) | 200 (all) | 403 |

### T11.3 — Cross-tenant 404

- Tenant A tiene assets {id-A1, id-A2, id-A3}.
- Admin de tenant B hace GET/PATCH/DELETE sobre cada id-A: cada
  response es 404 (no 403). Verificar que no se leak existencia.

### T11.4 — Superadmin cross-tenant

- `superadmin` GET list: incluye assets de tenant A y tenant B.
  Verificar paginación `{items, total, limit, offset}`.
- `superadmin` GET by-id sobre asset de tenant A: 200.
- `superadmin` PATCH/DELETE sobre asset de tenant A: 200/204; el
  `tenant_id` del asset permanece inalterado.
- `superadmin` POST sin `tenant_id` en el body: 422 `tenant_id is
  required`.
- `superadmin` POST con `tenant_id` de tenant A válido: 201 con
  `tenant_id = A` en el response.
- `superadmin` GET `?export=csv`: 200 con CSV de todos los tenants;
  `Content-Type: text/csv`.

### T11.5 — Unicidad (409)

- POST duplicado `(tenant_id, type, value)`: 409.
- PATCH que genera duplicado (B=(ip,1.2.3.4) → value=192.0.2.1 ya de
  A): 409.

### T11.6 — Paginación y validación de query

- `limit=50, offset=0` con 150 assets: `items=50, total=150`.
- `limit=500`: 422 con mensaje `limit must be ≤ 200`.

### T11.7 — Eventos (spy)

- Spy sobre `EventBus.publish`. Por cada mutación exitosa, el spy
  registra un evento con `stream="asset.events"` y `event_type`
  correcto: POST → `asset.created`; PATCH → `asset.updated` con
  `changed_fields` reales; DELETE → `asset.deleted`.
- Test negativo: si `db.commit()` lanza, NO se publica ningún evento.

### T11.8 — Hygiene de response

- GET by-id devuelve exactamente seis campos públicos declarados:
  `id`, `type`, `value`, `tenant_id`, `created_at`, `updated_at`.
- Ningún campo ORM interno (`status`, `asset_metadata`,
  `created_by_user_id`, `raw_input`) aparece en la respuesta JSON
  serializada.

### T11.9 — Validación semántica (422)

- `type=ip, value=not-an-ip` → 422 con mensaje esperado.
- `type=subnet, value=192.168.0.0/40` → 422 `value must be a valid
  CIDR`.
- `type=domain, value=-bad-.com` → 422 `value must be a valid FQDN`.

### T11.10 — Cobertura del comando de tests

- `uv run pytest tests/unit/test_assets.py tests/api/test_assets.py
  -v` corre limpio, sin warnings de `--strict-markers`.

---

## Fase T12 — Verify y entrega

### T12.1 — Verificación local

- `uv run alembic upgrade head` sobre BD de tests.
- `uv run alembic check` (sin drift).
- `uv run pytest tests/unit/test_assets.py tests/api/test_assets.py
  -v`.
- Suite completa `uv run pytest` para detectar regresiones en F1 u
  otros módulos.
- `grep -rn "\.name" app/modules/assets/ tests/` no devuelve
  referencias huérfanas legítimas.
- `grep -rnE "['\"]host['\"]" app/ tests/` revisado: las únicas
  apariciones restantes son las legítimas (literales de role distinto
  a asset_type, si los hay).

### T12.2 — Lint y tipos

- `uv run ruff check app/modules/assets/ app/modules/assets tests/
  tests/api/migrations/versions/`.
- `uv run mypy app/modules/assets/` sin nuevos errores.

### T12.3 — Gate al usuario

Antes de merge:

- Resumen de cambios por archivo (lista de Fase T1..T9 con su diff de
  LOC).
- Resultado de la matriz RBAC 30/30 (esperado) y de los escenarios
  del spec (esperado PASS).
- Riesgos residuales declarados:
  - Commit seguido de Redis no es atómico (aceptado sin outbox).
  - `auditor_externo` queda explícitamente fuera de F2.
  - Downgrade puede perder contenido histórico de `hostname`
    (vacío → NULL).
- Pregunta al usuario: "¿Apruebas la entrega del slice 1 Assets para
  merge a `sdd/prd-v2-vertical-f2`?".

### T12.4 — Commit final

Solo tras aprobación humana. Mensaje:

```text
feat(f2-assets): implement Slice 1 Assets (vertical CRUD)

- Alembic migration aligning assets to 6 types + value + unique
- AssetService async with per-type semantic validation
- Asset router with RBAC allowlist + three-layer tenant scoping
- Superadmin explicit POST/PATCH/DELETE routes
- Asset events (created/updated/deleted) on asset.events stream
- 30-combination RBAC parametrized test suite
- Tests cover spec scenarios end-to-end

Refs: design.md D-001..D-012; spec/f2-assets/spec.md.
```text

PR contra `sdd/prd-v2-vertical-f2` con descripción anclada al slice
1 del PRD F2.

---

## Riesgos residuales declarados (heredados del design)

| Riesgo | Mitigación |
| --- | --- |
| Rename `name` → `value` rompe callers | Grep preventivo antes del merge; tests de regresión cubren la nueva superficie. |
| Unique `(tenant_id, asset_type, value)` falla con duplicados preexistentes | Precondición explícita en T1.2 con `RuntimeError` accionable. |
| Cambio `host` → `hostname` deja comparaciones | Grep de literales y revisión manual. |
| Downgrade pierde datos si hay `subnet`/`cloud_resource` | Precondición en T1.3 aborta antes del DDL. |
| Composite identity y RLS son defensas complementarias | Tests confirman coincidencia entre predicado router y policy. |
| Commit seguido de Redis no es atómico | Aceptado en este slice; log/métrica; outbox en slice posterior. |
| `auditor_externo` se difiere a F3 | Cualquier intento de meterlo se rechaza en review. |
| Normalización colisiona (IPv6 canonicalization) | Documentado en tests; 409 es deseado. |
| Override de `get_db_with_tenant` en tests no aplica RLS por sí mismo | Fixture `tenant_client` resuelve D-010; tests antiguos quedan válidos hasta refactor. |

## Out of scope (declarado en design)

- Scans, schedules, detección, deduplicación, lifecycle de vulns.
- 9 funciones LLM (slice 8).
- PDFs y reportes.
- Consumidores de eventos (este slice publica solamente).
- Dashboard y métricas agregadas.
- Celery, Celery Beat, workers, tareas background.
- Nmap, LangGraph, webhooks, frontend.
