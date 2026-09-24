# Slice 2 — Scans — Specification

## Propósito

Definir los requisitos formales para el CRUD vertical de `Scan` sobre los assets disponibles en el slice 1. Este slice persiste definiciones de scan en estado `pending`; no inicia ni ejecuta scans.

## Requisitos

### Requirement: Endpoints CRUD existen y están protegidos por RBAC

El router DEBE exponer `POST /api/v1/scans`, `GET /api/v1/scans`, `GET /api/v1/scans?asset_id={asset_id}`, `GET /api/v1/scans/{id}`, `PATCH /api/v1/scans/{id}` y `DELETE /api/v1/scans/{id}`. Las seis operaciones DEBEN aplicar las siguientes decisiones RBAC exactas; `own` limita el alcance al tenant autenticado y `cross` permite alcance global solo a `superadmin`.

| Operación | admin | analyst | viewer | superadmin | ingestor |
| --- | --- | --- | --- | --- | --- |
| `POST /scans` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |
| `GET /scans` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `GET /scans?asset_id={asset_id}` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `GET /scans/{id}` | ✓ own | ✓ own | ✓ own | ✓ cross | ✗ |
| `PATCH /scans/{id}` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |
| `DELETE /scans/{id}` | ✓ own | ✗ | ✗ | ✓ cross | ✗ |

#### Scenario: RBAC POST — admin crea en su tenant

- GIVEN un usuario `admin` autenticado con tenant propio
- WHEN solicita `POST /api/v1/scans` con datos válidos para su tenant
- THEN la respuesta DEBE ser `201 Created`

#### Scenario: RBAC POST — analyst queda denegado

- GIVEN un usuario `analyst` autenticado
- WHEN solicita `POST /api/v1/scans`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC POST — viewer queda denegado

- GIVEN un usuario `viewer` autenticado
- WHEN solicita `POST /api/v1/scans`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC POST — superadmin crea cross-tenant explícitamente

- GIVEN un `superadmin` autenticado y un `tenant_id` objetivo explícito
- WHEN solicita `POST /api/v1/scans` con un asset de ese tenant
- THEN la respuesta DEBE ser `201 Created`

#### Scenario: RBAC POST — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `POST /api/v1/scans`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC listado sin filtro — admin consulta su tenant

- GIVEN un usuario `admin` autenticado
- WHEN solicita `GET /api/v1/scans`
- THEN la respuesta DEBE ser `200 OK` y solo DEBE incluir scans de su tenant

#### Scenario: RBAC listado sin filtro — analyst consulta su tenant

- GIVEN un usuario `analyst` autenticado
- WHEN solicita `GET /api/v1/scans`
- THEN la respuesta DEBE ser `200 OK` y solo DEBE incluir scans de su tenant

#### Scenario: RBAC listado sin filtro — viewer consulta su tenant

- GIVEN un usuario `viewer` autenticado
- WHEN solicita `GET /api/v1/scans`
- THEN la respuesta DEBE ser `200 OK` y solo DEBE incluir scans de su tenant

#### Scenario: RBAC listado sin filtro — superadmin consulta globalmente

- GIVEN un `superadmin` autenticado
- WHEN solicita `GET /api/v1/scans`
- THEN la respuesta DEBE ser `200 OK` y PUEDE incluir scans de todos los tenants visibles

#### Scenario: RBAC listado sin filtro — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `GET /api/v1/scans`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC listado por asset — admin consulta su tenant

- GIVEN un usuario `admin` autenticado y un asset de su tenant
- WHEN solicita `GET /api/v1/scans?asset_id={asset_id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC listado por asset — analyst consulta su tenant

- GIVEN un usuario `analyst` autenticado y un asset de su tenant
- WHEN solicita `GET /api/v1/scans?asset_id={asset_id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC listado por asset — viewer consulta su tenant

- GIVEN un usuario `viewer` autenticado y un asset de su tenant
- WHEN solicita `GET /api/v1/scans?asset_id={asset_id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC listado por asset — superadmin consulta cross-tenant

- GIVEN un `superadmin` autenticado y un asset de cualquier tenant
- WHEN solicita `GET /api/v1/scans?asset_id={asset_id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC listado por asset — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `GET /api/v1/scans?asset_id={asset_id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC GET by-id — admin consulta su tenant

- GIVEN un usuario `admin` autenticado y un scan de su tenant
- WHEN solicita `GET /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC GET by-id — analyst consulta su tenant

- GIVEN un usuario `analyst` autenticado y un scan de su tenant
- WHEN solicita `GET /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC GET by-id — viewer consulta su tenant

- GIVEN un usuario `viewer` autenticado y un scan de su tenant
- WHEN solicita `GET /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC GET by-id — superadmin consulta cross-tenant

- GIVEN un `superadmin` autenticado y un scan de cualquier tenant
- WHEN solicita `GET /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC GET by-id — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `GET /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC PATCH — admin modifica su tenant

- GIVEN un usuario `admin` autenticado y un scan de su tenant
- WHEN solicita `PATCH /api/v1/scans/{id}` con un cambio válido
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC PATCH — analyst queda denegado

- GIVEN un usuario `analyst` autenticado
- WHEN solicita `PATCH /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC PATCH — viewer queda denegado

- GIVEN un usuario `viewer` autenticado
- WHEN solicita `PATCH /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC PATCH — superadmin modifica cross-tenant

- GIVEN un `superadmin` autenticado y un scan de cualquier tenant
- WHEN solicita `PATCH /api/v1/scans/{id}` con un cambio válido
- THEN la respuesta DEBE ser `200 OK`

#### Scenario: RBAC PATCH — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `PATCH /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC DELETE — admin elimina en su tenant

- GIVEN un usuario `admin` autenticado y un scan de su tenant
- WHEN solicita `DELETE /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `204 No Content`

#### Scenario: RBAC DELETE — analyst queda denegado

- GIVEN un usuario `analyst` autenticado
- WHEN solicita `DELETE /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC DELETE — viewer queda denegado

- GIVEN un usuario `viewer` autenticado
- WHEN solicita `DELETE /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

#### Scenario: RBAC DELETE — superadmin elimina cross-tenant

- GIVEN un `superadmin` autenticado y un scan de cualquier tenant
- WHEN solicita `DELETE /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `204 No Content`

#### Scenario: RBAC DELETE — ingestor queda denegado

- GIVEN un usuario `ingestor` autenticado
- WHEN solicita `DELETE /api/v1/scans/{id}`
- THEN la respuesta DEBE ser `403 Forbidden`

### Requirement: Tenant scoping en tres capas

El aislamiento de `Scan` DEBE reforzarse mediante la FK compuesta `(asset_id, tenant_id) → assets(id, tenant_id)`, la policy PostgreSQL `rls_scans` y un predicado explícito `Scan.tenant_id == current_user.tenant_id` para usuarios tenant. Los accesos by-id o por `asset_id` que no sean visibles en el tenant DEBEN devolver `404 Not Found`, no `403 Forbidden`.

#### Scenario: La FK compuesta rechaza una asociación entre tenants

- GIVEN un asset que pertenece al tenant A
- WHEN se intenta persistir un scan con `tenant_id` del tenant B y ese `asset_id`
- THEN la relación DEBE rechazarse por integridad
- AND la API DEBE responder `404 Not Found` al cliente tenant que no puede ver el asset

#### Scenario: RLS y filtro explícito ocultan un scan cross-tenant by-id

- GIVEN el tenant A tiene un scan y un usuario autorizado pertenece al tenant B
- WHEN el usuario solicita `GET`, `PATCH` o `DELETE` sobre el id del scan A
- THEN cada respuesta DEBE ser `404 Not Found`
- AND la consulta de usuario tenant DEBE incluir el predicado de tenant

#### Scenario: El listado tenant no filtra datos de otros tenants

- GIVEN los tenants A y B tienen scans
- WHEN un usuario autorizado del tenant B solicita el listado sin filtro
- THEN los `items` y `total` DEBEN describir únicamente scans del tenant B

#### Scenario: Superadmin usa alcance global deliberado

- GIVEN un `superadmin` autenticado bajo contexto RLS de superadmin
- WHEN lista, obtiene, actualiza o elimina un scan de cualquier tenant
- THEN la consulta NO DEBE añadir un predicado de tenant
- AND la operación DEBE aplicar el contrato RBAC correspondiente

### Requirement: Asociación con Asset existente y del tenant correcto

POST DEBE requerir un `asset_id` existente y visible del tenant objetivo. El `superadmin` DEBE proporcionar `tenant_id` explícito al crear; un usuario tenant DEBE crear solo con su propio tenant. Un asset inexistente o no visible DEBE producir `404 Not Found` y nunca DEBE permitir una asociación entre tenants.

#### Scenario: POST asocia un asset visible del tenant objetivo

- GIVEN un asset existente del tenant A
- WHEN un admin de A crea un scan con ese `asset_id`
- THEN la respuesta DEBE ser `201 Created`
- AND el scan persistido DEBE tener el `tenant_id` A

#### Scenario: POST con asset inexistente o no visible devuelve 404

- GIVEN un `asset_id` inexistente o perteneciente a otro tenant
- WHEN un admin tenant solicita `POST /api/v1/scans`
- THEN la respuesta DEBE ser `404 Not Found`
- AND NO DEBE persistirse un scan

#### Scenario: Superadmin debe declarar tenant objetivo coherente

- GIVEN un `superadmin` autenticado
- WHEN crea un scan con `tenant_id` explícito y un asset de otro tenant
- THEN la respuesta DEBE ser `404 Not Found`
- AND NO DEBE persistirse una relación scan/asset cross-tenant

### Requirement: Tipos y configuración de scan se validan por contrato

El sistema DEBE aceptar exactamente los tipos públicos `discovery`, `vulnerability`, `web` y `full`, persistidos como `scan_type`. `config` DEBE ser un objeto JSON y DEBE rechazar claves desconocidas. Para que este CRUD no especifique comportamiento de ejecución, los contratos mínimos son: `discovery` requiere `host_discovery` booleano; `vulnerability` requiere `checks`, una lista no vacía de identificadores no vacíos; `web` requiere `paths`, una lista no vacía de rutas que comienzan con `/`; y `full` requiere los tres campos `host_discovery`, `checks` y `paths` con las mismas reglas. Los demás campos DEBEN rechazarse.

#### Scenario: Configuración discovery válida

- GIVEN un POST o PATCH efectivo de tipo `discovery` con `config={"host_discovery": true}`
- WHEN se valida la request
- THEN la request DEBE aceptarse

#### Scenario: Configuración vulnerability válida

- GIVEN un POST o PATCH efectivo de tipo `vulnerability` con `config={"checks": ["baseline"]}`
- WHEN se valida la request
- THEN la request DEBE aceptarse

#### Scenario: Configuración web válida

- GIVEN un POST o PATCH efectivo de tipo `web` con `config={"paths": ["/"]}`
- WHEN se valida la request
- THEN la request DEBE aceptarse

#### Scenario: Configuración full válida

- GIVEN un POST o PATCH efectivo de tipo `full` con `config={"host_discovery": true, "checks": ["baseline"], "paths": ["/"]}`
- WHEN se valida la request
- THEN la request DEBE aceptarse

#### Scenario: Configuración incompatible devuelve 422 con mensaje específico

- GIVEN un config sin una clave requerida, con tipo de valor inválido o con una clave desconocida
- WHEN se valida un POST o el config efectivo de PATCH
- THEN la respuesta DEBE ser `422 Unprocessable Entity`
- AND el detalle DEBE identificar la clave inválida o faltante y el `scan_type` efectivo

### Requirement: Lifecycle y timestamps operativos son de solo lectura

Los únicos valores persistibles de `status` son `pending`, `running`, `completed`, `failed` y `cancelled`, conforme a `chk_scans_status`. En este slice, POST DEBE fijar `status="pending"` y `started_at` y `completed_at` nulos. POST y PATCH NO DEBEN aceptar `status`, `started_at` ni `completed_at`; ninguna transición manual está disponible en esta API. Las transiciones y timestamps operativos corresponden a slices posteriores de ejecución.

#### Scenario: Crear una definición no ejecuta ni altera el lifecycle

- GIVEN un POST válido de scan
- WHEN el scan se crea
- THEN la respuesta DEBE contener `status="pending"`
- AND `started_at` y `completed_at` DEBEN ser nulos
- AND NO DEBE iniciarse una tarea, proceso o comando de ejecución

#### Scenario: PATCH rechaza falsificación de lifecycle

- GIVEN un scan existente y un usuario con permiso de PATCH
- WHEN solicita PATCH con `status`, `started_at` o `completed_at`
- THEN la respuesta DEBE ser `422 Unprocessable Entity`
- AND el lifecycle almacenado DEBE permanecer sin cambios

### Requirement: No se impone unicidad de negocio de nombre pending

Este slice NO DEBE declarar ni simular `uq_scans_tenant_asset_name_pending`. Los nombres repetidos y múltiples definiciones `pending` equivalentes para el mismo `(tenant_id, asset_id, name)` DEBEN permitirse mientras no vulneren una constraint persistida existente. Los conflictos de integridad de constraints existentes que puedan traducirse a dominio DEBEN responder `409 Conflict`.

#### Scenario: Dos definiciones pending pueden compartir nombre

- GIVEN un tenant y asset existentes con un scan `pending` llamado `weekly`
- WHEN un admin crea otro scan `pending` con el mismo asset y nombre
- THEN la respuesta DEBE ser `201 Created`
- AND ambos scans DEBEN permanecer persistidos

### Requirement: Eventos CRUD se publican después del commit

Toda mutación exitosa DEBE hacer `flush`, commit exitoso y solo después publicar un evento en el stream `scan.events`. Los eventos DEBEN usar los tipos `scan.created`, `scan.updated` y `scan.deleted`; un fallo de publicación posterior al commit NO DEBE revertir la mutación ya confirmada.

#### Scenario: POST publica scan.created

- GIVEN un POST válido que confirma su transacción
- WHEN finaliza el commit
- THEN se DEBE publicar en `scan.events` un evento `scan.created`
- AND el payload DEBE incluir `event_id`, `event_type`, `timestamp`, `scan_id`, `tenant_id`, `asset_id`, `name`, `type`, `status`, `config` y `created_at`

#### Scenario: PATCH publica scan.updated

- GIVEN un PATCH válido que confirma su transacción
- WHEN finaliza el commit
- THEN se DEBE publicar en `scan.events` un evento `scan.updated`
- AND el payload DEBE incluir `event_id`, `event_type`, `timestamp`, `scan_id`, `tenant_id` y `changed_fields`

#### Scenario: DELETE publica scan.deleted

- GIVEN un DELETE válido que confirma su transacción
- WHEN finaliza el commit
- THEN se DEBE publicar en `scan.events` un evento `scan.deleted`
- AND el payload DEBE incluir `event_id`, `event_type`, `timestamp`, `scan_id` y `tenant_id`

### Requirement: Listados paginados y filtrados son deterministas

Los listados DEBEN devolver `{items, total, limit, offset}`. `limit` DEBE tener default `50`, mínimo `1` y máximo `200`; `offset` DEBE ser mayor o igual que `0`. Los resultados DEBEN ordenarse por `created_at DESC, id DESC`. El filtro opcional `asset_id` DEBE afectar tanto `items` como `total` y DEBE respetar tenant scoping.

#### Scenario: Listado devuelve página y total

- GIVEN un alcance visible con 150 scans
- WHEN se solicita `GET /api/v1/scans?limit=50&offset=0`
- THEN la respuesta DEBE contener 50 `items`, `total=150`, `limit=50` y `offset=0`
- AND los items DEBEN ordenarse por `created_at DESC, id DESC`

#### Scenario: Parámetros de paginación inválidos devuelven 422

- GIVEN un usuario autorizado
- WHEN solicita un listado con `limit=0`, `limit=201` u `offset=-1`
- THEN la respuesta DEBE ser `422 Unprocessable Entity`

#### Scenario: Filtro asset_id ausente o no visible devuelve 404

- GIVEN un usuario tenant autorizado
- WHEN solicita el listado filtrado para un asset inexistente o no visible
- THEN la respuesta DEBE ser `404 Not Found`
- AND la respuesta NO DEBE revelar scans de otros tenants

### Requirement: Responses usan una whitelist pública exacta

Las responses de create, get, patch y cada elemento de listado DEBEN incluir exactamente `id`, `tenant_id`, `asset_id`, `name`, `type`, `status`, `config`, `started_at`, `completed_at`, `created_at` y `updated_at`. `type` es el nombre público de `scan_type`. La respuesta NO DEBE serializar implícitamente atributos ORM ni campos futuros no documentados.

#### Scenario: Response expone únicamente la whitelist pública

- GIVEN un scan existente con atributos ORM adicionales presentes ahora o en el futuro
- WHEN se devuelve desde POST, GET, PATCH o listado
- THEN el JSON DEBE contener exactamente los once campos públicos documentados
- AND `status` y `config` DEBEN exponerse por contrato como campos públicos de la definición
- AND NO DEBE incluir atributos internos o no documentados
