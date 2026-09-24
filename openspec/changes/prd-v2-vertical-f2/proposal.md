# Propuesta: PRD v2 — Construcción Vertical F2

## Intención

Construir el backend F2 completo módulo por módulo, sin presión de tiempo, siguiendo estrictamente el ciclo SDD (proposal → spec → design → tasks → apply → verify → archive) para cada slice vertical.

El `prd-v1-mvp-junio` (archivado como `2026-06-28-prd-v1-mvp-junio`) fue diseñado con una restricción temporal artificial de junio 2026. Aquella restricción ya no aplica. Este PRD reemplaza completamente al anterior y se alinea con la filosofía del master roadmap: "primero limpio, luego sano, luego construye en vertical".

## Estado Actual (junio 2026)

### F1 — ~85% completo

- Auth (JWT + refresh + denylist + CSRF), tenants (RLS), users, roles, rate limiting
- Modelos, servicios, routers, schemas y tests completos
- ~520 tests pasan
- **Pendiente**: restaurar índices eliminados, actualizar `last_login_at` en login, limpiar tests API vacíos, revisar rate limiting/CSRF

### F2 Modelos — completos

- Asset, Scan, Vulnerability, Report con migraciones R1/R2 encadenadas
- Tests unitarios de modelos y tenant isolation
- Composite FKs para aislamiento multi-tenant
- **Falta**: schemas, servicios, routers, tests de API

### Infraestructura

- FastAPI + PostgreSQL + Redis + Alembic + uv
- Event bus sobre Redis Streams
- Sin Celery workers, sin Nmap, sin LangGraph
- Sin frontend

## Alcance

### Slice 0: Sanear F1

Cerrar F1 antes de construir F2. Issues conocidos y acotados:

- Restaurar índices `ix_users_email_lower` y `ix_users_tenant_active`
- Actualizar `last_login_at` en login
- Eliminar `request_headers` muerto en login
- Eliminar tests API vacíos o con aserciones débiles
- Revisar rate limiting y CSRF

### Slices 1-4: Backend F2 — CRUD vertical completo

Cada módulo (Assets, Scans, Vulnerabilities, Reports) con:

- Schemas Pydantic (Create, Update, Response)
- Servicios asíncronos con tenant scoping
- Routers FastAPI con RBAC
- Tests unitarios + API

### Slices 5-9: Backend F2 — Infraestructura y agentes

- Nmap executor seguro
- Celery + Beat para tareas asíncronas
- Dashboard con métricas agregadas
- Pipeline de enriquecimiento LLM
- LangGraph agent pipeline

### Fuera de alcance (por ahora)

- Frontend (Fase 3 del roadmap)
- Deploy (Fase 4 del roadmap)
- Notificaciones email
- Escaneos en tiempo real

## Filosofía

> No avances rápido a costa de deuda estructural.
> Primero limpio, luego sano, luego construye en vertical.
> Cada módulo: estudiar → especificar → diseñar → tasks → aplicar → testear → verificar → archivar.
> Construye slices verticales completos. No abandones capas horizontales.

- Sin deadlines artificiales
- Sin cherry-picks de ramas viejas de F2
- Sin código sin tests
- TDD estricto (`strict_tdd: true`)
- Tenant isolation desde el día uno
- Mensajes en español

## Orden de Ejecución

```
Slice 0 (Heal F1) → Slice 1 (Assets) → Slice 2 (Scans) → Slice 3 (Vulnerabilities)
                                              ↘ Slice 5 (Nmap) → Slice 6 (Celery)
                  → Slice 4 (Reports) ↗                          ↘ Slice 8 (LLM)
                                              → Slice 7 (Dashboard) → Slice 9 (LangGraph)
```

## Criterios de Éxito

- [ ] F1 cerrado: tests verdes, migraciones limpias, login funcional, sin tests vacíos
- [ ] Assets: CRUD completo con tests, tenant isolation verificada
- [ ] Scans: CRUD con máquina de estados, eventos al bus, validación de cuota
- [ ] Vulnerabilities: CRUD con fingerprint SHA-256, deduplicación, transiciones de estado
- [ ] Reports: CRUD completo, preparado para generación async de PDF
- [ ] Nmap executor seguro (sin shell=True, con timeout)
- [ ] Celery worker funcional con Redis broker
- [ ] Dashboard con 5 métricas en F2 (10 incluyendo las diferidas a F3) y caché Redis
- [ ] Pipeline LLM con 9 funciones de enriquecimiento
- [ ] LangGraph agent pipeline (nodos definidos en design de slice 9)
- [ ] 0 regresiones en tests existentes
- [ ] Alembic heads siempre con una sola cabeza

## No Negociables

- Sin código importante sin proposal, spec, design, tasks, apply, verify, archive
- Sin merge sin verify
- No copiar F2 viejo a ciegas
- Tenant isolation: `tenant_id`, composite FKs, RLS, tests cross-tenant, filtrado en router
- Slices pequeñas
- Aprender antes de producir

## Riesgos

| Riesgo | Mitigación |
| -------- | ------------ |
| Quemarse | Slices pequeñas con checkpoints claros |
| Deuda estructural | SDD completo por slice, sin atajos |
| Fugas multi-tenant | Tests de tenant isolation en cada slice |
| Migraciones peligrosas | Auditoría de migraciones en cada verify |
| AI generando deuda no revisada | AI como asistente, no reemplazo; revisión línea por línea |

## Decisiones de elicitación

Cerradas en 2 sesiones: 2026-09-02 (flujo principal, roles, asset types, schedules, nmap, LLM enrichment, proveedor) + 2026-09-04 (bus eventos, webhooks, dashboard, PDFs, plan enforcement, vulnerable-target, status enum, granularidad). El quinto rol cross-tenant (`auditor_externo`) fue evaluado y **diferido a F3** (ver nota al pie del bloque de roles).

### Roles del tenant en F2 (4 con capacidad en Assets) + 1 diferido a F3

Los cinco roles canónicos persistidos en `chk_valid_role` (`app/modules/users/models.py:30`) son `viewer`, `analyst`, `ingestor`, `admin`, `superadmin`. Sobre Assets, cuatro de esos cinco tienen capacidad (la que se describe abajo) y `ingestor` está explícitamente denegado para los seis endpoints del slice 1 (sin capacidad de lectura, escritura ni export). `ingestor` se mantiene como literal válido en F1/F2 sin cambios; su alcance funcional sobre Assets es vacío por diseño. `auditor_externo` no es un rol nuevo: NO existe en F2; se difiere a F3.

| Rol | Capacidades sobre Assets (slice 1) |
| --- | --- |
| `admin` PyME | CRUD total: assets, scans, vulns, reports, schedules, webhooks |
| `analista` (`analyst`) | Lee vulns enriquecidas, marca status (los 5 estados), descarga PDFs |
| `viewer` | Solo dashboard (las 5 métricas) + listado de assets (read-only) |
| `superadmin` | **Único rol cross-tenant en F2**: gestiona tenants, planes, límites y exportación global |
| `ingestor` | Sin capacidad sobre Assets (denegado en los 6 endpoints del slice 1); su alcance propio pertenece a slices posteriores de ingesta |
| `auditor_externo` | **Diferido a F3.** Read-only cross-tenant con export a CSV/JSON; sin acciones. En F2 no existe como rol activo: ni en seeds, ni en `chk_valid_role`, ni en RBAC, ni en policies RLS, ni en export. Su modelado (literales, RLS cross-tenant read-only, ampliación de seeds) entra al slice F3 correspondiente, no a los slices 1–9 de F2. |

### Tipos de asset (6)

`ip`, `domain`, `hostname`, `web_app`, `subnet` (CIDR), `cloud_resource`. Validación por tipo en service layer.

### Schedules — Modelo B

- Varios schedules por asset (ej: rápido 30min + profundo diario).
- Configuración vía API en F2 (POST/PATCH/DELETE endpoints).
- Frecuencias iniciales: 30min y 1h. Configurables por `admin`.
- Manual también permitido (trigger explícito vía endpoint).

### Nmap executor

- TCP SYN + UDP.
- Rango: top-1000 puertos en F2 (configurable si PyME pide más).
- Flags: `-sV` (servicios y versiones), `-O` (detección de SO), `--script=vuln` (NSE).
- Output: raw XML + vulns parseadas (ambas guardadas).
- **Prohibido**: `--script=exploit` (read-only por seguridad).

### LLM enrichment — 9 funciones por vulnerabilidad

1. Resumen ejecutivo
2. Descripción técnica
3. Análisis de explotabilidad
4. Severidad contextualizada
5. Remediación concreta
6. Impacto al negocio
7. Referencias adicionales (CVE/CWE/NVD/MITRE)
8. Plan de mitigación priorizado
9. Hardening general

### Proveedor LLM: OpenRouter

- Auth: Bearer token (API key en `.env`).
- Endpoint: `https://openrouter.ai/api/v1/chat/completions` (OpenAI-compatible).
- Reusar `OpenAICompatProvider` en `app/core/llm/providers.py` con swap de `base_url`.
- Dev: `inclusionai/ling-flash-3.0:free`.
- Prod: Gemini 3.8 Flash ($0.75/$3.75 por M tokens) o Claude Fable 5.1 ($10/$50).

### Bus de eventos interno — 4 categorías

| Categoría | Eventos |
| --- | --- |
| Scan lifecycle | `scan.requested`, `scan.started`, `scan.progress`, `scan.completed`, `scan.failed` |
| Vulnerability lifecycle | `vuln.detected`, `vuln.severity_changed`, `vuln.status_changed`, `vuln.enrichment_ready` |
| Asset lifecycle | `asset.created`, `asset.updated`, `asset.deleted`, `asset.scan_scheduled` |
| Report lifecycle | `report.requested`, `report.generated`, `report.ready`, `report.failed` |

### Webhooks out

**Sí, configurables por tenant**. El `admin` PyME define URL destino + secret + filtro por tipo de evento. Útil para SIEM/Slack/Teams del cliente.

### Dashboard — 5 métricas (F2)

1. Total assets monitored
2. Vulns by severity (count: critical / high / medium / low / info)
3. Scan coverage % (last 24h)
4. Open vs resolved trend (30d)
5. Scan success rate %

**Diferidas a F3** (con frontend): MTTR, top affected assets, top recurring CVEs, mean scan duration, KEV-flagged.

### Reportes PDF (3 tipos)

| PDF | Audiencia | Secciones |
| --- | --- | --- |
| `completo-explicativo` | admin PyME / auditoría interna | (1) Resumen ejecutivo · (2) Hallazgos priorizados + enrichment · (3) Plan de remediación priorizado · (4) Anexo técnico + raw output |
| `menos-tecnico` | directivos / clientes no técnicos | (1) Resumen en lenguaje claro · (2) Tabla de urgencia · (3) Pasos a seguir priorizados |
| `mas-tecnico` | pentesters / auditores / TI | (1) Cabecera técnica · (2) CVEs/CWEs con CVSS y exploit availability · (3) Comandos reproducibles · (4) Raw output nmap |

### Plan enforcement

- **3 tiers**: `free`, `pro`, `enterprise`.
- **Dimensiones limitadas**: `assets_max`, `scans_per_day`.
- **Sin límite** (todos los tiers): `ai_enrichment_level` (enrichment completo siempre) y `report_types` (los 3 PDFs disponibles siempre).
- Valores concretos por tier: se definen en `tasks.md` del slice enforcement (a planificar).

### Out-of-scope confirmado para F2

- **vulnerable-target Docker** — fuera. Tests E2E usan mocks/assets sintéticos o cherry-pick post-F2.
- Frontend → Fase 3.
- Deploy → Fase 4.
- Notificaciones email / Escaneos en tiempo real.

### Status de vulnerabilidad — 5 estados

`open` → `acknowledged` → `in_progress` → `fixed` (branch lateral: `wont_fix`).

**Requiere migración**: el modelo actual tiene enum `open/fixed`. La migración actualiza el enum PG y los defaults. Mapping: `fixed` actual → `fixed` nuevo (sin pérdida de datos).

### Granularidad de slices

**9 slices fijos** (PRD v2 tal cual). Sin sub-slices.
