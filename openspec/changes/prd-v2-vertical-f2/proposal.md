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
- [ ] Dashboard con 10 métricas y caché Redis
- [ ] Pipeline LLM con 8 funciones de enriquecimiento
- [ ] LangGraph agent pipeline de 5 nodos
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
|--------|------------|
| Quemarse | Slices pequeñas con checkpoints claros |
| Deuda estructural | SDD completo por slice, sin atajos |
| Fugas multi-tenant | Tests de tenant isolation en cada slice |
| Migraciones peligrosas | Auditoría de migraciones en cada verify |
| AI generando deuda no revisada | AI como asistente, no reemplazo; revisión línea por línea |
