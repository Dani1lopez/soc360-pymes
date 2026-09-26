# Revisión integral — soc360-pymes (2026-09-26)

Revisión **solo lectura** sobre `main` @ `d16f310` (F2 slice 3). No se modificó código.
Alcance: rendimiento, código muerto, seguridad, errores de código, calidad y sobreingeniería de tests.

## Método

- Lectura manual de todo `app/` (~11,9k líneas), migraciones, Docker/CI y una muestra representativa de `tests/` (~33k líneas).
- Herramientas: `vulture` (código muerto), `ruff`, `mypy`.
- Suite ejecutada como en CI (Postgres 16 y Redis efímeros, rol `soc360_app` NOBYPASSRLS):
  `pytest -m "not toxiproxy and not redis_pressure"` → **1489 passed, 1 skipped, 2 xfailed, 0 fallos, 16 min 15 s**.
- Verificación empírica del hallazgo S1 (petición sin token contra una app real con `redis-cli monitor`).
- Se cruzaron los resultados con `docs/audits/qa-audit-2026-09-19.md`. Al final hay una tabla con lo que sigue abierto.

Leyenda: 🔴 alta · 🟠 media · 🟡 baja. **[V]** = verificado empíricamente, **[C]** = deducido leyendo el código con alta confianza.

---

## Resumen ejecutivo

| Área | Veredicto |
|---|---|
| Seguridad | La base es sólida: RLS, JWT con algoritmo fijado, denylist fail-closed, bcrypt con igualación de tiempos y cookies estrictas. Aun así hay **fallos de autorización reales**: lock adquirido antes de autenticar, un admin puede anular a otro admin, spoofing de IP en el rate-limit y un DoS de lockout por email. |
| Errores de código | Hay 3 bugs funcionales serios en el event bus y en el ciclo de sesiones: consumidores duplicados entre workers, JTIs que crecen sin límite y la configuración de refresh ignorada. La imagen Docker sigue sin poder arrancar. |
| Rendimiento | Para la escala de una PYME no hay cuellos de botella críticos. Sí hay **crecimiento de memoria sin límite en Redis**, que tiene política `noeviction`: bastan streams sin consumidor y sets de JTI para provocar la caída total de la autenticación. También se hacen 2 round-trips a Redis por request y hay RLS que no usa índices. |
| Código muerto | Aproximadamente **1.300 líneas de producción sin uso**: el subsistema LLM completo (9 proveedores), Celery, contracts/LangGraph, catálogos de "flow policy", funciones de revocación alternativas, el módulo `reports` y `agents`. |
| Sobreingeniería | Es el mayor problema estructural. Hay infraestructura de resiliencia y observabilidad de nivel "plataforma" (29 FlowIds, 12 métricas, locks distribuidos con HMAC, DLQ con contador persistente) para un bus de eventos cuyo **único handler hace un `logger.info`**, y para 3 streams que **nadie consume**. |
| Tests | La suite está en verde y cubre bien RBAC, RLS y concurrencia. Pero hay unos **~5.900 LOC de tests para ~900 LOC de infraestructura de resiliencia** (6,6:1), tests que fijan constantes muertas, tests que leen README/pyproject/Dockerfile y tests cuyo resultado depende del **título del PR**. Además, el 90 % del tiempo de setup se va en bcrypt. |

---

## 1. Seguridad

### 🔴 S1 — `DELETE /tenants/{id}` adquiere el lock distribuido **antes** de autenticar [V]
`app/modules/tenants/router.py:111` declara `db: TenantDeactivationDBDep` antes que `current_user: SuperadminDep`. FastAPI resuelve las dependencias en orden, así que `get_tenant_deactivation_db` (`app/dependencies/lock_deps.py`), que solo depende de `get_db` y `get_redis`, ejecuta `SET NX` en Redis con cualquier petición anónima.
Reproducción: una petición sin token devuelve 401, pero `redis-cli monitor` muestra `"SET" "lock:auth_tenant_deactivate_lock:…"`.
Impacto: un atacante anónimo puede escribir en Redis y competir por el lock. Como `_ACTIVE_TOKENS` es global por proceso (ver E4), un superadmin legítimo recibe 503 al instante.
Arreglo: declarar `current_user` primero, o hacer que la dependencia de lock dependa de `require_superadmin`.

### 🔴 S2 — Un admin puede neutralizar a otro admin del mismo tenant [C]
`app/modules/users/router.py:154-169` solo impide que un admin cambie `is_active` de otro admin. En cambio, **sí** permite:
- degradar su rol (`role=viewer`) y luego desactivarlo con PATCH o DELETE, lo que esquiva la regla "un admin no puede desactivar a otro admin";
- cambiar su **email**, que es el identificador de login, y dejarlo fuera de su cuenta.

`can_assign_role` (`app/core/security.py`) existe pero no se usa en ninguna parte.
Arreglo: si `target` tiene rol ≥ admin y quien actúa no es superadmin, rechazar cualquier cambio.

### 🟠 S3 — IP del rate-limit falsificable detrás de proxy [C]
`app/modules/auth/router.py:52` toma el **primer** valor de `X-Forwarded-For`, que controla el cliente. Con `TRUSTED_PROXIES` configurado, el atacante envía `X-Forwarded-For: <ip aleatoria>` en cada intento y el bloqueo por IP nunca se activa. Debe tomarse el último salto que no sea de confianza (recorrer de derecha a izquierda).

### 🟠 S4 — DoS de bloqueo de cuentas por email, con escalado acumulativo [C]
`app/core/rate_limit.py:171`: por cada fallo por encima del umbral, `locked_until = max(now, locked_until) + lockout`. Un atacante que solo conozca el email de la víctima suma, por ejemplo, 24 h por intento. Con esto puede bloquear indefinidamente a cualquier usuario, incluido el superadmin.
Hay además un segundo contador independiente en `auth/service.py` (`login_attempts:*`, 10/15 min), así que existen dos mecanismos de lockout solapados.
Recomendación: un solo mecanismo, con un techo máximo absoluto y lockout por el par (IP, email) en lugar de solo por email.

### 🟠 S5 — PATCH de tenant con `is_active=false` esquiva el lock de desactivación [C]
`DELETE /tenants/{id}` usa el lock distribuido, pero `PATCH` con `is_active: false` (`tenants/service.py:184`) ejecuta la misma desactivación masiva sin lock. Existen dos caminos para la misma operación y solo uno está protegido.

### 🟠 S6 — `LOCK_KEY_SECRET` ausente se acepta en producción → 500 [C]
`app/core/config.py:312` solo valida la longitud **si no es `None`**. Sin la variable, la app arranca y cualquier desactivación de usuario o tenant falla con `ValueError` y devuelve 500 (`dist_lock._lock_key_secret`). Además, `.env.example` lo deja vacío.

### 🟠 S7 — Pendientes de la auditoría del 19-sep (siguen abiertos)
- `/health/db/indexes` no tiene autenticación y expone nombres del catálogo.
- `/refresh` no detecta la reutilización de un refresh token rotado (no hay revocación de la familia de tokens).
- El pre-check de rate-limit hace *fail-open* ante cualquier excepción que no sea `RedisError` (`auth/router.py:113` y los 3 endpoints restantes).
- Falta `FORCE ROW LEVEL SECURITY`.
- El redactor de logs solo compara nombres exactos (`app/core/logging.py:7`): `access_token` o `refresh_token` no se redactan.
- `verify_password` lanza excepción con un hash malformado.

### 🟡 S8 — Menores
- CSP `default-src 'self'` (`app/core/middleware.py:11`) **rompe Swagger UI** (`/api/docs` carga assets desde un CDN) en development y staging.
- `echo=True` en development (`database.py:44`) vuelca SQL con parámetros (hashes, `token_hash`) al log.
- La política de contraseñas es incoherente: `UserCreate` solo exige longitud ≥ 12, mientras que `change-password` exige también mayúscula, minúscula y dígito.
- No hay límite de tamaño de body ni de listas o dicts (`vulnerability_metadata: dict`, `config.paths: list`). Es posible un DoS de memoria con JSON grandes.
- `/refresh` acepta un `old_jti` de un token de **otro** usuario sin comprobar que `sub == user.id` (`auth/router.py:189`).

---

## 2. Errores de código (bugs funcionales)

### 🔴 E1 — Event consumer: mismo nombre en todos los workers + XCLAIM de todo el PEL con idle 0 [C]
- `app/main.py:150`: cada worker de gunicorn crea el consumer con `consumer_name="soc360-lifespan"`.
- `app/event_bus/consumer.py:88-128`: `read_pending` lee **todo** el PEL del grupo (sin filtrar por consumer) y hace `XCLAIM min_idle_time=0`. Así roba mensajes que otro worker está procesando en ese momento.

Resultado: con N workers, los eventos se procesan **por duplicado**, y un mensaje cuyo handler falla se reintenta en bucle cerrado (0,1 s) en todos los workers.
Arreglo: un nombre único por proceso (`hostname-pid`), `XAUTOCLAIM` con `min_idle_time` > 0 y filtrado por consumer en `XPENDING`.

### 🔴 E2 — El set `active_jtis:{user}` crece sin límite [C]
- `track_jti` (`security.py:234`) hace `SADD` **sin TTL**.
- `/refresh` (`auth/router.py:189`) extrae `old_jti` con `decode_access_token`, que **rechaza tokens expirados**. Refrescar con el access token expirado es el caso normal en una SPA, así que el JTI viejo nunca se saca del set.
- Cuando el tope de 5 sesiones revoca la sesión más antigua, no limpia su JTI.

Impacto:
- Unos 600 JTIs por usuario y semana con tokens de 15 min.
- `revoke_all_user_access_tokens` hace un `SET` **secuencial** por cada JTI. Cambiar la contraseña o desactivar un usuario pasa a costar miles de round-trips, y el tiempo puede superar el TTL del lock (30 s).
- Consumo de memoria en un Redis con `noeviction` (ver P1).

Arreglo: guardar los JTIs en un ZSET con `exp` como score y purgar con `ZREMRANGEBYSCORE`, o fijar un `EXPIRE` en el set; además, decodificar `old_jti` con `verify_exp=False`.

### 🔴 E3 — La imagen Docker no puede arrancar (pendiente del 19-sep, sigue igual) [C]
- `gunicorn` no está en `pyproject.toml` ni en `uv.lock`.
- El `Dockerfile` no copia `gunicorn_conf.py` ni `migrations/`.
- `gunicorn_conf.py` no define `worker_class=uvicorn.workers.UvicornWorker` ni `bind`. Con los valores por defecto se usan workers sync y se escucha en `127.0.0.1`, inaccesible desde fuera del contenedor.
- El contenedor corre como root y no tiene `HEALTHCHECK`.

### 🟠 E4 — Lock distribuido: la detección de "reentrada" es global por proceso y solo hay un reintento [C]
- `_ACTIVE_TOKENS` (`dist_lock.py:314/353`) es un dict de módulo. Si **otra request concurrente del mismo worker**, de otro usuario, tiene el lock, la segunda recibe `lock_reentry` (503) al instante en vez de esperar.
- `wait_timeout_seconds=2.0` es engañoso: se hace **un solo** reintento tras 0,1–0,5 s de jitter.
- No hay auto-renovación: `renew()` no se llama nunca (vulture), así que una transacción de más de 30 s pierde el lock sin enterarse.

### 🟠 E5 — `REFRESH_TOKEN_EXPIRE_DAYS` se ignora en BD [C]
`auth/service.py:51` fija `REFRESH_TOKEN_EXPIRE_DAYS = 7` como constante, que es la que se usa para `expires_at` en BD (línea 329). La cookie, en cambio, usa `settings.REFRESH_TOKEN_EXPIRE_DAYS`. Si se cambia la variable de entorno, cookie y BD divergen.

### 🟠 E6 — PATCH de usuario con email de otro tenant → 500 [C]
`users/service.py:164`: `_is_email_taken` se ejecuta bajo el contexto RLS del admin y solo ve su propio tenant. Si el email ya existe en otro tenant, la comprobación pasa, el `flush` choca con `UNIQUE(email)` y la `IntegrityError` no se captura (a diferencia de `create_user`). Resultado: 500.

### 🟠 E7 — Doble escritura sin outbox (pendiente del 19-sep, ahora en 3 módulos) [C]
En assets, scans y vulnerabilities se hace `commit` y después `publish`. Si Redis falla tras el commit, el cliente recibe 503 aunque el dato ya se guardó; si reintenta, obtiene 409. Como nadie consume esos streams (ver D2), es un fallo visible para el usuario sin ningún beneficio.

### 🟠 E8 — El límite `max_assets` del plan no se aplica nunca [C]
`Tenant.max_assets` se calcula y se valida en `tenants/service.py`, pero `assets/service.create_asset` no lo comprueba. Los planes free, starter, pro y enterprise no tienen ningún efecto.

### 🟡 E9 — Menores
- `login` no registra en el contador del servicio los intentos contra un email inexistente, porque se lanza el error antes de `_record_failed_attempt` (`service.py:393`). El router sí los registra.
- `refresh_tokens`: la rama `else: async with db.begin()` (`service.py:508`) es inalcanzable, porque `get_db` siempre abre una transacción. `record.revoked_at is not None` también es redundante.
- `bus.py:85,279`: `str(v) if hasattr(v, "__str__") else v` siempre es verdadero, porque todos los objetos tienen `__str__`.
- `bus.py`: aparece `__import__("datetime")` en línea.
- `lifespan`: tras `task.cancel()` no se hace `await` del task.
- El `Literal` de estados de vulnerabilidad en `contracts.py` (`acknowledged`, `resolved`) contradice el CHECK de la BD (`fixed`).
- Scans: se puede editar un scan en cualquier estado; no hay máquina de estados, aunque existen FlowIds `SCAN_START`, `SCAN_COMPLETE` y `SCAN_CANCEL`.
- `mypy`: 52 errores. La mayoría son falsos positivos de Pydantic sin plugin. Los reales son `F821` (`LLMProvider` y `EventBus` sin importar en anotaciones) y `DBAPIError.sql_error` inexistente (`auth/service.py:254`).
- `ruff`: 5 × F821, 1 × F841 y 1 × F541 en `app/`, y 42 avisos en `tests/`. **CI no ejecuta ni ruff ni mypy.**

---

## 3. Rendimiento

| # | Sev. | Hallazgo | Ubicación |
|---|---|---|---|
| P1 | 🔴 | **Redis con `noeviction` y crecimiento sin límite.** Hay 3 streams sin consumidor (`asset.events`, `scan.events`, `vulnerability.events`), cada uno con hasta 100k entradas, más `events:system.auth.login` (el consumer solo lee `auth.login`), más los sets de JTI de E2. Cuando Redis llena `maxmemory`, rechaza escrituras; la autenticación es fail-closed, así que **se cae todo el login**. | `bus.py`, `security.py:234`, `docker-compose.yml` |
| P2 | 🟠 | 2 round-trips a Redis por request autenticada: `PING` (`check_redis_healthy`) y luego `EXISTS`. El PING sobra, porque `EXISTS` ya falla si Redis está caído. En login, refresh, logout y change-password hay otros PINGs redundantes. | `dependencies/auth.py:64` |
| P3 | 🟠 | Las políticas RLS usan `tenant_id::text = current_setting(...)`. El cast de la columna impide usar el índice (hoy lo salva el predicado explícito de la app). `rls_refresh_tokens` evalúa una subconsulta sobre `users` por fila. Conviene `tenant_id = current_setting(...)::uuid`. | migraciones `712a827b0929`, `8f2c1a4b9d7e`, `bfca7016cbb7` |
| P4 | 🟠 | `RateLimiter`: `check` hace 2 `HGETALL` secuenciales (el comentario dice "in parallel"); `record_failure` hace de 4 a 5 round-trips por clave, sin atomicidad (condición de carrera en el escalado). Todo cabe en un script Lua o un pipeline. | `core/rate_limit.py:109-174` |
| P5 | 🟡 | Revocación de un usuario: un `SET` por JTI, secuencial. En tenants, `asyncio.gather` lanza N usuarios × M JTIs en paralelo sobre un pool de 20 conexiones. La versión "batch" (`revoke_all_user_access_tokens_batch`) existe pero no se usa. | `security.py`, `tenants/service.py:41` |
| P6 | 🟡 | Paginación con `OFFSET` y `count(*)` en cada página, ordenada por `created_at DESC, id DESC`, sin índice compuesto `(tenant_id, created_at, id)`. Aceptable para PYMEs. | services de assets, scans y vulns |
| P7 | 🟡 | `SecurityHeadersMiddleware` y `HTTPSRedirectMiddleware` usan `BaseHTTPMiddleware`, con sobrecoste conocido. Mejor como middleware ASGI puro. | `core/middleware.py` |
| P8 | 🟡 | `_ensure_group_exists` (XGROUP CREATE) se ejecuta en cada iteración del consumer. En cada worker se crea al arrancar un `httpx.AsyncClient` para un LLM que no se usa. | `consumer.py`, `main.py:128` |
| P9 | 🟡 | **Tests:** cada test que usa `seed_data` hace 6 `bcrypt.gensalt()` con coste 12 y 6 logins: unos 3,5 s de setup por test. Los 25 tests más lentos son todos de setup. Usar `rounds=4` en tests, o hashes precomputados a nivel de sesión, reduciría la suite de 16 min a unos pocos minutos. | `tests/conftest.py:124` |

---

## 4. Código muerto

Detectado con `vulture` y confirmado con grep (uso en `app/` frente a `tests/`):

| Código | Líneas aprox. | Estado |
|---|---|---|
| **Subsistema LLM completo**: `app/core/llm/*` (9 proveedores, retry, redacción), `llm_deps.get_llm`, `LLMError*`, `_provider_names.py`, unas 25 variables de config LLM | ~750 | Ningún endpoint lo usa. Solo se instancia al arrancar para escribir un log. Aun así, **`GROQ_API_KEY` es obligatoria por defecto** para arrancar. |
| `celery` (dependencia y smoke test en CI) | — | Ni un import en `app/`. |
| `app/core/contracts.py` (`EnrichedFinding`, `ScanState` para LangGraph, `UpsertVulnerabilitiesResult`, `VALID_*`) | 107 | Sin uso. LangGraph ni siquiera es dependencia. |
| `outage.py`: `FlowPolicy`, `RetryableOp`, `ALL_FLOW_IDS` y FlowIds sin productor (`SCAN_*_LOCK`, `*_SERVICE`, `ACCOUNT_LOCKOUT_CHECK`…) | ~120 | Solo se usan en tests. |
| `security.py`: `revoke_tokens_by_jtis`, `revoke_all_user_access_tokens_batch`, `get_active_jtis`, `secure_compare`, `can_assign_role`, `get_token_remaining_seconds` | ~110 | Solo tests. (`can_assign_role` debería usarse; ver S2.) |
| `dist_lock.py`: `renew`, `is_lost`, `_LOCK_RESOURCE_*`, imports "opcionales" protegidos con `try/except ImportError` para métricas que sí existen | ~60 | — |
| Event bus: `get_consumer`, `reconnect_and_resume`, `EventConsumer.delete`, `_INFLIGHT_DLQ` y `drain_dlq_tasks` (el set nunca se llena) | ~70 | — |
| `metrics.SEVEN_METRICS`, `PartialFailureError` (solo tenants), `AssetError`, `ScanError`, `VulnerabilityError`, `ReportError` | ~30 | — |
| `users/service.get_user_by_email`; `assets/service.get_asset` (el router consulta directamente) | ~20 | — |
| Módulo `reports` (modelo y tabla sin endpoints), `app/agents/` vacío, rol `ingestor` (no se admite en ningún endpoint) | ~80 | Deuda de roadmap. |
| Config sin lectura: `EVENT_STREAM_MAXAGE_SECONDS`, `LOCK_RETRY_AFTER_SECONDS` (validado, nunca leído), `USE_OLLAMA`, `OLLAMA_*`, `POSTGRES_*` | — | — |
| Validaciones duplicadas: la de `REDIS_URL` aparece dos veces (`__init__` y `model_validator`); la de CORS `*` dos veces (validator y `create_app`); `LOCK_MIN_TTL_SECONDS` en config y en `dist_lock` | — | — |

**Total: ~1.300 líneas de producción eliminables, y en proporción varios miles de líneas de tests asociados** (sección 6).

---

## 5. Sobreingeniería

1. **Event bus para un `logger.info`.** Redis Streams con consumer groups, recuperación de PEL, contador de reintentos persistente con TTL, DLQ, monitorización de lag, 12 métricas y "flows". El único handler (`_handle_auth_login`) solo loguea. Otros 3 streams no tienen consumidor. Además, la implementación tiene los bugs E1 y P1. Recomendación: hasta que exista un consumidor real, un log estructurado en el login basta. Cuando llegue, usar una tabla outbox en Postgres.
2. **Catálogo de resiliencia normativo.** 29 FlowIds, un mapa `FlowPolicy` que no consulta nadie y un enum `RetryableOp` que "debe tener exactamente seis miembros". Todo ello está fijado por tests. Es documentación de diseño convertida en código de producción.
3. **Locks distribuidos con claves HMAC por tenant** para desactivar un usuario o un tenant. Esas operaciones ya son idempotentes en BD; un `SELECT … FOR UPDATE` o un advisory lock de Postgres (ya usado en `_acquire_session_cap_lock`) resolvería lo mismo sin Redis, sin `LOCK_KEY_SECRET` y sin S1, S6 ni E4.
4. **Abstracción LLM multi-proveedor** (9 proveedores) antes de tener un solo caso de uso.
5. **`_is_lock_timeout_error` con 4 capas** de detección "multi-driver", cuando el proyecto solo usa asyncpg. `metrics_auth._extract_header` es un "pipeline de 4 pasos" con referencias a "design rev 16".
6. **Duplicación entre slices F2.** `_add_tenant_predicate`, `_violates_constraint`, `_effective_tenant_id`, `_caller_tenant_id` y el mapeo de errores a HTTP están copiados 3 veces (assets, scans, vulns). La validación de la config de scans se hace dos veces: modelo Pydantic y `_validate_scan_config`.
7. **Rate-limit copiado y pegado 4 veces** en `auth/router.py`, unas 25 líneas por endpoint. Debería ser una sola dependencia.
8. **Docstrings y comentarios que narran el proceso** ("PR5a", "design rev 9", "T4.2", "issue #133") en lugar de explicar el código. Envejecen mal.

---

## 6. Análisis de tests

### Cifras
- 1.242 funciones de test (1.489 casos con parametrización) en unas 33k líneas: una proporción test/producción de **2,8:1**.
- Distribución: `unit` 830 tests (18,7k LOC), `integration` 173, `api` 84, `sdd` 49, raíz 97.

| Área | LOC de test | LOC de producción | Ratio |
|---|---|---|---|
| Resiliencia (outage, locks, métricas, toxiproxy, fail-closed) | ~5.900 (32 ficheros) | ~900 | **6,6:1** |
| Event bus (7 ficheros unitarios + 2 E2E + esquemas) | ~4.300 (11 ficheros) | ~620 | 7:1 |
| LLM (feature inexistente) | ~630 | ~750 muertas | — |
| Assets, scans y vulns (funcionalidad de negocio) | ~6.900 | ~2.300 | 3:1 |

### Lo bueno
- La suite está en verde y es reproducible, y el test de BD se ejecuta con el rol `soc360_app` NOBYPASSRLS, así que **RLS se ejerce de verdad**.
- Matriz RBAC parametrizada completa, tests de aislamiento cross-tenant, concurrencia real (advisory lock, carrera de refresh) e inyección de fallos con Toxiproxy.
- La transacción externa con savepoints evita fugas de estado entre tests.

### Problemas
1. **Tests que fijan código muerto o constantes**: `test_outage_primitives.py` (778 LOC: "catalog has exactly 29 items", "RetryableOp has exactly six members"), `test_metrics_registry.py`, `test_llm_*.py`, `test_security.py` (que prueba `secure_compare`, `revoke_tokens_by_jtis`, etc.). Congelan la sobreingeniería: borrar código muerto rompe tests.
2. **Tests de proceso en lugar de comportamiento** (`tests/sdd/`): comprueban que el README contiene `uv sync`, que el `pyproject` tiene ciertas líneas, que `celery --help` funciona (y Celery no se usa), que el `docker-compose` no tiene `build:`, o analizan con AST que no haya imports en línea (`test_imports.py`).
3. **El resultado depende del título del PR**: `test_uv_migration.py:223` cambia su aserción según `SDD_PR_CONTEXT`, que se extrae del título del PR en CI. Un test no debe depender de metadatos de GitHub.
4. **Duplicación por capas**: `tests/test_auth.py`, `tests/unit/test_auth.py` y `tests/integration/test_auth_integration.py` (y lo mismo para users y tenants). Hay además 7 ficheros de event bus, algunos nombrados por issue (`test_event_bus_issue_133.py`, `test_pr9_observability.py`, `test_security_migration.py`). Organizar por comportamiento y no por ticket.
5. **Alto acoplamiento a la implementación**: más de 50 usos de `_dispatch_event`, 46 de `_create_provider`, 34 de `_get_active_user`, 29 de `_consumer_loop`, etc. Los tests mockean internos privados, así que cualquier refactor rompe decenas de tests sin que cambie el comportamiento.
6. **Fixtures que esquivan el diseño**: `tests/conftest.py:423-500` tiene unas 60 líneas de parches para el singleton `_event_bus`, porque `auth.service` llama a `get_event_bus()` directamente en vez de recibirlo por inyección de dependencias. Es un síntoma del diseño, no del test.
7. **Huecos de cobertura en lo que sí importa** (ningún test detecta los bugs reales):
   - S1: el orden de las dependencias frente a la autenticación.
   - S2: un admin que degrada o cambia el email de otro admin.
   - E1: varios consumers o workers.
   - E2: refresh con un access token expirado y crecimiento de `active_jtis`.
   - E6: email duplicado en otro tenant en un PATCH.
   - E8: `max_assets`.
   - S3: `X-Forwarded-For` falsificado.
8. **Lentitud**: 16 min, dominados por bcrypt en las fixtures (P9). CI tampoco mide cobertura (no hay `pytest-cov`).
9. 3 warnings de corutinas que nunca se awaitean (`test_event_bus_redis.py`, `test_outage_primitives.py`). Son mocks mal configurados que pueden ocultar aserciones que no se ejecutan.

---

## 7. Plan recomendado (por prioridad)

1. **Seguridad y bugs (1–2 días)**: S1 (orden de dependencias), S2 (reglas admin sobre admin), S3 (XFF), E2 (TTL y limpieza de JTIs), E1 (nombre de consumer y XAUTOCLAIM), E5, E6 y S6. Añadir un test de regresión por cada uno.
2. **Despliegue**: E3 (gunicorn con worker uvicorn, bind, `COPY`, usuario no root) y añadir ruff, mypy y cobertura al CI.
3. **Reducción**: eliminar LLM, Celery, contracts, el catálogo `FlowPolicy`/`RetryableOp`, las funciones de revocación sin uso y los streams sin consumidor, junto con sus tests. Hacer `GROQ_API_KEY` opcional.
4. **Simplificación**: sustituir los locks de Redis de desactivación por locks de Postgres; unificar el rate-limit en una dependencia y en un solo mecanismo de lockout con techo; extraer helpers comunes de F2; aplicar `max_assets`.
5. **Tests**: `bcrypt rounds=4` en fixtures, fusionar los ficheros duplicados por capa, borrar los tests de proceso y de constantes, y dejar de mockear funciones privadas donde un test de API cubra el comportamiento.

---

## Anexo — Estado de los hallazgos de la auditoría del 2026-09-19

| ID previo | Estado |
|---|---|
| F2 Docker no arranca | **Abierto** (E3) |
| F3 sin `FORCE ROW LEVEL SECURITY` | **Abierto** (el riesgo depende del despliegue; en CI los tests usan `soc360_app` y RLS sí se ejerce) |
| F4 CI sin ruff/mypy | **Abierto** |
| F5 `verify_password` con hash malformado | **Abierto** |
| F7 `/health/db/indexes` sin auth | **Abierto** |
| F8 reuse detection en refresh | **Abierto** |
| F9 rate-limit *fail-open* | **Abierto** |
| F10 redacción de logs por coincidencia exacta | **Abierto** |
| F11 tests obsoletos / deriva de esquema | **Resuelto**: la suite está en verde (1489 passed) |
| F12 doble escritura sin outbox | **Abierto y extendido** a scans y vulns (E7) |
