# Slice 1 — Assets — Specification

## Propósito

Definir los requisitos formales para el CRUD vertical de `Asset` (slices 1 de los 9 de F2). Es el primer módulo construido sobre los modelos F2 ya existentes (`Asset`, composite FKs, RLS).

## Requisitos

### Requirement: Migration del modelo Asset a 6 tipos + campo `value` + unique

Una migración Alembic nueva DEBE transformar `app/modules/assets/models.py` así:

- Renombrar columna `name` (String 255, NOT NULL) → `value` (String 255, NOT NULL)
- Eliminar columna `hostname`
- Extender `chk_assets_asset_type` para incluir 2 valores nuevos: `'subnet'`, `'cloud_resource'`. Renombrar el literal `'host'` → `'hostname'` para alinear con la elicitación. Resultado: `IN ('hostname', 'domain', 'ip', 'web_app', 'subnet', 'cloud_resource')`
- Agregar `UniqueConstraint` `uq_assets_tenant_type_value` sobre `(tenant_id, asset_type, value)`
- Mantener `chk_assets_status` (es lifecycle, no vuln status)
- Mantener `uq_assets_id_tenant_id` (existe, no se duplica)

#### Scenario: La migration es reversible solo cuando NO hay filas con tipos nuevos

- GIVEN la migration fue aplicada sobre una BD con datos
- AND la BD NO contiene filas con `asset_type IN ('subnet', 'cloud_resource')`
- WHEN se ejecuta `alembic downgrade -1`
- THEN el `downgrade()` DEBE abortar explícitamente con `RuntimeError(...)` si encuentra filas con esos tipos, ANTES de cualquier DDL
- AND si la cuenta es cero, la columna `value` DEBE renombrarse de vuelta a `name`
- AND la columna `hostname` DEBE volver a existir (vacía si se había perdido contenido)
- AND `chk_assets_asset_type` DEBE volver a `IN ('host', 'domain', 'ip', 'web_app')`
- AND el UniqueConstraint `uq_assets_tenant_type_value` DEBE eliminarse
- AND el downgrade NO DEBE ejecutarse parcialmente: o completa todo el DDL o aborta antes del primer DDL con el `RuntimeError`

#### Scenario: Downgrade aborta antes del DDL cuando hay filas con tipos no soportados

- GIVEN la migration fue aplicada y la BD contiene al menos una fila con `asset_type='subnet'` o `asset_type='cloud_resource'`
- WHEN se ejecuta `alembic downgrade -1`
- THEN el `downgrade()` DEBE lanzar `RuntimeError` con mensaje accionable que mencione explícitamente los tipos y la cuenta de filas afectadas
- AND el `downgrade()` NO DEBE haber ejecutado ningún DDL previo (constraint `chk_assets_asset_type` de seis tipos sigue presente; columna `value` sigue renombrada; constraint `uq_assets_tenant_type_value` sigue presente)
- AND el operador DEBE resolver la condición (migrar las filas a uno de los cuatro tipos históricos o borrarlas) antes de reintentar el downgrade

#### Scenario: Datos existentes se preservan en el upgrade

- GIVEN la tabla `assets` tiene N filas antes de la migration
- WHEN se aplica `alembic upgrade head`
- THEN N filas DEBEN seguir existiendo con `value` poblado (antes `name`)
- AND el constraint `chk_assets_asset_type` actualizado DEBE incluir los 6 valores
- AND `uq_assets_tenant_type_value` DEBE estar presente

#### Scenario: Test unitario verifica el shape post-migration

- GIVEN la migration aplicada en una BD de test
- WHEN un test llama a `inspect(Asset)` y refleja contra el modelo
- THEN NO debe haber drift entre el modelo SQLAlchemy y la BD real (Alembic no detecta diferencias en `alembic check`)

### Requirement: Tipos de asset soportados (6)

El sistema DEBE soportar exactamente 6 tipos de asset: `ip`, `domain`, `hostname`, `web_app`, `subnet`, `cloud_resource`. Cada tipo tiene validación específica en la capa de service.

#### Scenario: Validación de `ip`

- GIVEN un POST con `type="ip"` y `value="192.0.2.42"` (IPv4 válida) o `value="2001:db8::1"` (IPv6 válida)
- WHEN se ejecuta la validación
- THEN la request DEBE aceptarse y persistirse

#### Scenario: Validación de `ip` rechaza valor no-IP

- GIVEN un POST con `type="ip"` y `value="not-an-ip"` o `value="999.999.999.1"`
- WHEN se ejecuta la validación
- THEN la request DEBE rechazarse con `422` y un mensaje `value must be a valid IPv4 or IPv6 address`

#### Scenario: Validación de `domain` rechaza FQDN inválido

- GIVEN un POST con `type="domain"` y `value="-bad-.com"` o `value="espacio .com"`
- WHEN se ejecuta la validación
- THEN la request DEBE rechazarse con `422` y un mensaje `value must be a valid FQDN`

#### Scenario: Validación de `subnet` rechaza CIDR inválido

- GIVEN un POST con `type="subnet"` y `value="192.168.0.0/40"` (prefijo fuera de rango) o `value="192.168.0.0/abc"`
- WHEN se ejecuta la validación
- THEN la request DEBE rechazarse con `422` y un mensaje `value must be a valid CIDR`

#### Scenario: Validación de `cloud_resource` acepta AWS ARN

- GIVEN un POST con `type="cloud_resource"` y `value="arn:aws:s3:::my-bucket"` (ARN válido)
- WHEN se ejecuta la validación
- THEN la request DEBE aceptarse y persistirse

### Requirement: Endpoints CRUD existen y están protegidos por RBAC

El router DEBE exponer `POST /api/v1/assets`, `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `PATCH /api/v1/assets/{id}`, `DELETE /api/v1/assets/{id}`. Cada endpoint aplica la matriz RBAC del slice.

Para la matriz RBAC de cada endpoint vs rol, ver la tabla siguiente. Los checks `✓` significan "permite"; `✗` significa "403 Forbidden". `own` = solo el propio tenant del usuario; `cross` = todos los tenants (caso especial único de `superadmin` en F2; `auditor_externo` se difiere a F3, ver proposal). El nombre canónico del rol es `analyst` (literal F1 persistido); en esta tabla se conserva como etiqueta funcional equivalente a `analista`.

Los cinco roles canónicos persistidos en `chk_valid_role` (`app/modules/users/models.py:30`) son `viewer`, `analyst`, `ingestor`, `admin`, `superadmin`. Sobre Assets solo cuatro de esos cinco tienen capacidad; `ingestor` está explícitamente denegado en los seis endpoints del slice (sin capacidad de lectura, escritura ni export). Esto NO añade un rol nuevo: `ingestor` ya existe en F1/F2 y se mantiene intacto, pero su alcance funcional sobre Assets es vacío por diseño. `auditor_externo` se difiere a F3 y NO aparece en esta matriz.

| Endpoint                  | admin | analyst | viewer | superadmin | ingestor |
|---------------------------|-------|---------|--------|------------|----------|
| POST /assets              | ✓     | ✗       | ✗      | ✓          | ✗        |
| GET /assets (list)        | ✓ own | ✓ own   | ✓ own  | ✓ cross    | ✗        |
| GET /assets/{id}          | ✓ own | ✓ own   | ✓ own  | ✓ cross    | ✗        |
| PATCH /assets/{id}        | ✓     | ✗       | ✗      | ✓          | ✗        |
| DELETE /assets/{id}       | ✓     | ✗       | ✗      | ✓          | ✗        |
| GET /assets?export=csv    | ✓ own | ✓ own   | ✓ own  | ✓ all      | ✗        |

#### Scenario: Cada endpoint respeta la matriz RBAC

- GIVEN un test parametrizado sobre los 6 endpoints × 5 roles canónicos = 30 combinaciones en total (18 con permiso distribuido entre `admin`/`analyst`/`viewer`/`superadmin` y 12 denegados: 6 de `ingestor` en los seis endpoints + 6 de `analyst`/`viewer` en POST/PATCH/DELETE). Los cinco roles canónicos son `viewer`, `analyst`, `ingestor`, `admin`, `superadmin`; cuatro tienen al menos una capacidad sobre Assets y `ingestor` no tiene ninguna.
- WHEN cada combinación se ejecuta contra el `httpx.AsyncClient` asíncrono del proyecto (fixture `client` de `tests/conftest.py`, no `fastapi.testclient.TestClient`) con sesión multi-tenant
- THEN la response DEBE coincidir exactamente con la matriz RBAC (✓ → 2xx, ✗ → 403)
- AND los 6 casos de `ingestor` DEBEN devolver `403 Forbidden` para los seis endpoints sin excepción

#### Scenario: RBAC — POST/PATCH/DELETE permitidos a `admin` y `superadmin`, denegados al resto

- GIVEN la matriz RBAC: POST/PATCH/DELETE permiten `admin` y `superadmin`; deniegan `analyst`, `viewer` e `ingestor`
- WHEN un usuario autenticado con rol `analyst` (o `viewer` o `ingestor`) intenta `POST /api/v1/assets`
- THEN la response DEBE ser `403 Forbidden`
- AND la misma denegación DEBE aplicarse a `PATCH /api/v1/assets/{id}` y `DELETE /api/v1/assets/{id}`
- AND un `superadmin` que ejecuta los mismos endpoints mutadores DEBE obtener el código de éxito previsto por la operación (201/200/204), sin que la matriz lea "solo `admin`" este caso

#### Scenario: RBAC — GET accesible para `admin`, `analyst`, `viewer` y `superadmin`; denegado a `ingestor`

- GIVEN la matriz RBAC: GET list/by-id/export permite `admin`, `analyst`, `viewer` y `superadmin`; deniega `ingestor`
- WHEN un usuario autenticado con rol `viewer` hace `GET /api/v1/assets`
- THEN la response DEBE ser `200 OK` con la lista (filtrada por tenant)
- AND un usuario `ingestor` que hace el mismo `GET /api/v1/assets` DEBE recibir `403 Forbidden`, sin que el filtro de tenant ni el response code enmascare la denegación

#### Scenario: RBAC — `superadmin` es el único con export cross-tenant en F2

- GIVEN un usuario con rol `superadmin`
- WHEN hace `GET /api/v1/assets?export=csv`
- THEN la response DEBE ser `200` con data de **todos los tenants** (cross-tenant by design)
- AND la response `Content-Type` DEBE ser `text/csv`
- AND NO existe todavía el rol `auditor_externo` en F2: este escenario no aplica al resto de roles porque ningún otro rol del slice 1 está autorizado a esa exportación global.

### Requirement: Tenant scoping en 3 capas

El tenant scoping DEBE estar reforzado en 3 capas independientes: composite FKs (`tenant_id` en cada tabla), RLS (políticas Postgres) y filtro explícito en el router.

#### Scenario: Composite FK impide asset sin tenant

- GIVEN un POST con `type="ip"` y `value="192.0.2.1"` pero **sin** `tenant_id` en el cuerpo
- WHEN la request llega al service
- THEN la request DEBE rechazarse con `422` (`tenant_id is required`)

#### Scenario: RLS impide GET cross-tenant

- GIVEN tenant A existe con un asset `id=42`
- AND tenant B existe sin ese asset
- AND un usuario autenticado pertenece a tenant B
- WHEN hace `GET /api/v1/assets/42`
- THEN la response DEBE ser `404 Not Found` (no `403`, para no leak existencia)

#### Scenario: DELETE cross-tenant devuelve 404

- GIVEN tenant A existe con asset `id=42`
- AND un `admin` autenticado pertenece a tenant B
- WHEN hace `DELETE /api/v1/assets/42`
- THEN la response DEBE ser `404 Not Found`

#### Scenario: Endpoints by-id cross-tenant devuelven 404

- GIVEN tenant A tiene assets {id-A1, id-A2, id-A3}
- AND tenant B tiene un admin autenticado
- WHEN el admin de tenant B hace GET /assets/{id-A1}, GET /assets/{id-A2}, PATCH /assets/{id-A1}, DELETE /assets/{id-A1}
- THEN cada response DEBE ser 404 (no leak existencia)

#### Scenario: List cross-tenant solo expone assets del propio tenant

- GIVEN tenant A tiene 3 assets, tenant B tiene 2 assets
- AND un admin de tenant B hace GET /assets
- THEN la response DEBE incluir exactamente los 2 assets de tenant B
- AND NO DEBE incluir ningún asset de tenant A

#### Scenario: POST cross-tenant desde admin de tenant B → 201 en su propio tenant

- GIVEN un admin autenticado de tenant B
- WHEN hace POST /assets con type="ip" y value="1.2.3.4"
- THEN la response DEBE ser 201 (es su propio tenant, no requiere target externo)
- AND el asset creado DEBE pertenecer a tenant B, NO a tenant A

### Requirement: Superadmin scoping explícito en list/by-id/POST

Los endpoints DEBEN distinguir entre usuarios tenant y `superadmin` con dos rutas de scoping bien definidas. Los usuarios tenant (cualquier rol excepto `superadmin`) mantienen predicados explícitos `Asset.tenant_id == current_user.tenant_id` y devuelven `404` (nunca `403`) ante cualquier acceso by-id fuera de su tenant. `superadmin` omite el predicado `tenant_id` en queries de listado y by-id, apoyándose en la policy RLS existente; en POST DEBE recibir `tenant_id` explícito en el body como tenant objetivo (no se permite POST sin `tenant_id` ni POST a su propio tenant implícito, porque no tiene tenant).

#### Scenario: Superadmin list expone assets de todos los tenants

- GIVEN tenant A tiene 2 assets, tenant B tiene 3 assets
- AND un `superadmin` autenticado (sin `tenant_id` propio) hace `GET /api/v1/assets`
- THEN la response DEBE incluir los 5 assets combinados (cross-tenant)
- AND la respuesta DEBE paginarse igual que para usuarios tenant (`items`, `total`, `limit`, `offset`)
- AND la query SQL NO DEBE añadir el predicado `Asset.tenant_id == ...`
- AND la policy RLS `rls_assets` vigente debe autorizar la lectura de todos los tenants bajo el contexto `app.is_superadmin = 'true'`

#### Scenario: Superadmin GET by-id recupera asset de cualquier tenant

- GIVEN tenant A tiene un asset `id=42`
- AND un `superadmin` autenticado hace `GET /api/v1/assets/42`
- THEN la response DEBE ser `200 OK` con el asset de tenant A
- AND la query SQL NO DEBE añadir el predicado `Asset.tenant_id == ...` (cross-tenant safe global query)

#### Scenario: Superadmin PATCH by-id actualiza asset de cualquier tenant

- GIVEN tenant A tiene un asset `id=42` con `value="192.0.2.1"`
- AND un `superadmin` autenticado hace `PATCH /api/v1/assets/42` con `{"value": "192.0.2.2"}`
- THEN la response DEBE ser `200 OK` con el asset actualizado
- AND el predicado SQL aplicado NO DEBE restringir por tenant
- AND el `tenant_id` del asset permanece inalterado (tenant A)

#### Scenario: Superadmin DELETE by-id elimina asset de cualquier tenant

- GIVEN tenant A tiene un asset `id=42`
- AND un `superadmin` autenticado hace `DELETE /api/v1/assets/42`
- THEN la response DEBE ser `204 No Content`
- AND la query SQL NO DEBE añadir el predicado `Asset.tenant_id == ...`

#### Scenario: Superadmin POST requiere `tenant_id` explícito en el body

- GIVEN un `superadmin` autenticado (sin tenant propio)
- WHEN hace `POST /api/v1/assets` con body `{"tenant_id": "<tenant-A-uuid>", "type": "ip", "value": "1.2.3.4"}`
- THEN la response DEBE ser `201 Created` con el asset creado bajo tenant A
- AND el router DEBE validar que el `tenant_id` del body existe y es distinto de NULL

#### Scenario: Superadmin POST sin `tenant_id` devuelve 422

- GIVEN un `superadmin` autenticado
- WHEN hace `POST /api/v1/assets` con body `{"type": "ip", "value": "1.2.3.4"}` (sin `tenant_id`)
- THEN la response DEBE ser `422` con detalle `tenant_id is required` (un superadmin no tiene tenant implícito)

#### Scenario: Usuarios tenant: by-id cross-tenant devuelve 404 (no 403)

- GIVEN tenant A tiene asset `id=42`
- AND un `admin` autenticado pertenece a tenant B
- WHEN hace `GET /api/v1/assets/42`, `PATCH /api/v1/assets/42` o `DELETE /api/v1/assets/42`
- THEN cada response DEBE ser `404 Not Found` (no leak de existencia)
- AND el predicado SQL `Asset.tenant_id == current_user.tenant_id` DEBE aplicarse siempre para usuarios tenant

#### Scenario: `ingestor` recibe 403 sin importar el tenant del recurso

- GIVEN un usuario `ingestor` autenticado pertenece a tenant A
- AND tenant A tiene un asset `id=42`
- WHEN hace `GET /api/v1/assets/42`, `POST /api/v1/assets`, `PATCH /api/v1/assets/42` o `DELETE /api/v1/assets/42`
- THEN cada response DEBE ser `403 Forbidden` (RBAC denegado, antes de cualquier evaluación de tenant scope)

### Requirement: Unicidad (tenant_id, type, value)

La combinación `(tenant_id, type, value)` DEBE ser única. No puede haber dos assets del mismo tenant con el mismo type y value.

#### Scenario: POST duplicado devuelve 409

- GIVEN tenant X tiene un asset `type="ip"`, `value="192.0.2.1"`
- WHEN un `admin` de tenant X intenta `POST` con la misma combinación
- THEN la response DEBE ser `409 Conflict`

#### Scenario: PATCH que genera duplicado devuelve 409

- GIVEN tenant X tiene assets `A=(ip, 192.0.2.1)` y `B=(ip, 192.0.2.2)`
- WHEN un `admin` intenta `PATCH B` para cambiar su value a `192.0.2.1`
- THEN la response DEBE ser `409 Conflict`

### Requirement: Eventos del bus se publican en mutaciones

Cada mutación exitosa DEBE publicar el evento correspondiente en el bus interno (Redis Streams).

#### Scenario: POST publica `asset.created`

- GIVEN un `admin` autenticado
- WHEN ejecuta `POST /api/v1/assets` con datos válidos
- THEN el bus DEBE recibir un mensaje en el stream `asset.events` con tipo `asset.created` y payload `{asset_id, tenant_id, type, value, created_at}`

#### Scenario: PATCH publica `asset.updated`

- GIVEN un asset existente
- WHEN se ejecuta `PATCH /api/v1/assets/{id}` con cambios válidos
- THEN el bus DEBE recibir un mensaje tipo `asset.updated` con `{asset_id, tenant_id, changed_fields}`

#### Scenario: DELETE publica `asset.deleted`

- GIVEN un asset existente
- WHEN se ejecuta `DELETE /api/v1/assets/{id}`
- THEN el bus DEBE recibir un mensaje tipo `asset.deleted` con `{asset_id, tenant_id}`

### Requirement: Paginación de listado

El listado `GET /api/v1/assets` DEBE soportar paginación con `limit` (default 50, max 200) y `offset`.

#### Scenario: Paginación funciona y devuelve metadatos

- GIVEN un tenant con 150 assets
- WHEN hace `GET /api/v1/assets?limit=50&offset=0`
- THEN la response DEBE incluir `items` (50), `total=150`, `limit=50`, `offset=0`

#### Scenario: limit fuera de rango se rechaza

- GIVEN un tenant autenticado
- WHEN hace `GET /api/v1/assets?limit=500`
- THEN la response DEBE ser `422` (`limit must be ≤ 200`)

### Requirement: Respuestas no leaken campos sensibles

Las respuestas `GET` DEBEN devolver solo los campos whitelisted en el schema Pydantic de Response.

#### Scenario: Response no incluye campos internos; `created_at` y `updated_at` son públicos por diseño

- GIVEN un asset existente
- WHEN se ejecuta `GET /api/v1/assets/{id}`
- THEN el JSON DEBE incluir los seis campos públicos: `id`, `type`, `value`, `tenant_id`, `created_at`, `updated_at`
- AND `created_at` y `updated_at` son explícitamente públicos por contrato del slice 1 (no son timestamps internos): se exponen en cada response para soporte de auditoría y ordenamiento por cliente
- AND NO DEBE incluir: `created_by_user_id`, `raw_input`, `status` (asset status se difiere), `asset_metadata`, ni cualquier otro campo interno o no documentado en este spec

### Requirement: Tests unitarios + API

Cada requisito de este spec DEBE tener al menos un test unitario (service) y un test API (router). Los tests API DEBEN ejecutarse contra el `httpx.AsyncClient` asíncrono del proyecto (definido en `tests/conftest.py` con `ASGITransport(app=app)`), no contra `fastapi.testclient.TestClient`, que es síncrono y no se usa en la base actual.

**Importante**: `httpx.AsyncClient` actúa solo como transport/cliente HTTP contra la app ASGI; por sí mismo no establece contexto RLS ni tenant. El override de `get_db` definido en `tests/conftest.py` (que produce un `yield db_session`) tampoco invoca `set_tenant_context()`: el contexto RLS solo se materializa cuando se ejecuta la dependencia tenant-aware `get_db_with_tenant()` (`app/dependencies/db_deps.py`), que invoca `set_tenant_context(db_session, current_user.tenant_id, current_user.is_superadmin)` con el `current_user` resuelto por `get_current_user`. Por tanto, los tests API de aislamiento multi-tenant DEBEN, según corresponda:

- (a) sobrescribir explícitamente `get_db_with_tenant` con un override que también invoque `set_tenant_context(db_session, current_user.tenant_id, current_user.is_superadmin)` para el rol y tenant del test; o bien
- (b) invocar `await set_tenant_context(db_session, tenant_id, is_superadmin)` directamente sobre la sesión del test antes de la request, replicando el contrato de `get_db_with_tenant`.

NO DEBE afirmarse que el override plano de `get_db` aplica automáticamente RLS: ese override solo reemplaza la sesión de base de datos, no el contexto Postgres.

#### Scenario: Test suite del slice 1 corre y pasa

- GIVEN los tests en `tests/unit/test_assets.py` y `tests/api/test_assets.py`
- WHEN se ejecuta `uv run pytest tests/unit/test_assets.py tests/api/test_assets.py`
- THEN todos los tests DEBEN pasar
- AND el `--strict-markers` no DEBE reportar warnings

#### Scenario: Test suite corre desde la convención real del proyecto

- GIVEN los tests viven en `tests/unit/test_assets.py` y `tests/api/test_assets.py` (verificado por `ls tests/unit/` y `ls tests/api/`)
- WHEN se ejecuta `uv run pytest tests/unit/test_assets.py tests/api/test_assets.py`
- THEN todos los tests DEBEN pasar
