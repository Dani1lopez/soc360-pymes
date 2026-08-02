# SOC360-PyMEs — SOC como Servicio para Pequeñas y Medianas Empresas

[🇺🇸 English](README.md)

![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115.6-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)
![Redis](https://img.shields.io/badge/Redis-7-DC382D.svg)
![Tests](https://img.shields.io/badge/tests-1091-brightgreen.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)
![Ruff](https://img.shields.io/badge/linter-ruff-261C15.svg)
![Mypy](https://img.shields.io/badge/types-mypy-2E6DB4.svg)

---

## Por qué SOC360-PyMEs

Las pequeñas y medianas empresas (PyMEs) enfrentan las mismas amenazas cibernéticas que las grandes corporaciones, pero rara vez cuentan con el presupuesto para construir o mantener un Centro de Operaciones de Seguridad (SOC) 24/7. **SOC360-PyMEs** elimina esa brecha al entregar un backend SaaS multi-tenant que proporciona operaciones de seguridad de nivel empresarial a una fracción del costo.

- **Problema**: Las PyMEs carecen de equipos de seguridad dedicados, gestión de vulnerabilidades y detección de amenazas en tiempo real.
- **Solución**: Una plataforma SOC-as-a-Service con descubrimiento automatizado de activos, análisis de vulnerabilidades potenciado por IA, aislamiento por tenant y procesamiento escalable de eventos.

---

## Estado Actual

| Fase | Estado | Descripción |
|------|--------|-------------|
| **F0** | ✅ Completado | Arquitectura y Modelo de Datos — 23 ADRs, 13 tablas DB, modelo de seguridad |
| **F1** | ✅ Completado | Base del Backend — Auth, tenants, usuarios, RLS, eventos, LLM — 1091 tests pasando |
| **F2** | 🔄 En Progreso | Agente de Vulnerabilidades — Executor Nmap, agente LangGraph, CRUD asset/vuln, dashboard, reportes PDF |
| **F3** | 📋 Planificado | Tiempo Real — WebSockets, ingestión de logs, detección de anomalías |
| **F4** | 📋 Planificado | Frontend — React 18 + TypeScript + Vite (MVP Junio 2026) |
| **F5** | 📋 Planificado | Agentes Extra — Cumplimiento, Inteligencia |
| **F6** | 📋 Planificado | Avanzado — Email, reportes PDF, Redis TLS |
| **F7** | 📋 Planificado | QA + Prod — E2E tests, CI/CD, deploy |

---

## Features Principales

| Feature | Descripción |
|---------|-------------|
| **Autenticación y Seguridad** | JWT access (15min) + rotación de refresh (7d, cookie HttpOnly). Denylist JTI vía Redis. Bloqueo de login (10 intentos / 15min). Rate limiting. Protección CSRF. Security headers. Sanitización PII. |
| **Multi-Tenant (RLS)** | Row-Level Security vía PostgreSQL `SET LOCAL`. Contexto de tenant por transacción. 4 planes: Free (10 assets), Starter (25), Pro (100), Enterprise (500). |
| **RBAC** | Roles jerárquicos: viewer < analyst/ingestor < admin < superadmin. CHECK constraints refuerzan reglas de tenant. Autoprotección evita escalada de privilegios. |
| **Event Bus** | Redis Streams con eventos tipados Pydantic, consumer groups, XACK, Dead Letter Queue, auto-reconexión y monitoreo de lag. |
| **Abstracción LLM** | Provider Protocol con 8 proveedores. Groq (llama-3.3-70b) por defecto. Caché singleton. `llm_safe_complete()` nunca lanza excepciones. Redacción de credenciales. |

---

## Arquitectura de Alto Nivel

```mermaid
graph TB
    Client["Client / Frontend"] --> API["FastAPI App<br/>(Uvicorn)"]
    API --> PG[("PostgreSQL 16<br/>(RLS per Tenant)")]
    API --> Redis[("Redis 7<br/>Denylist · Cache · Events")]
    Redis --> Worker["Celery Worker<br/>(Nmap + LLM)"]
    Worker --> Target["Vulnerable Target<br/>(Isolated Docker Net)"]
    Worker --> PG
    Worker --> LLM["LLM Provider<br/>(Groq · OpenAI · etc)"]
```

La plataforma sigue un patrón de monolito modular. FastAPI gestiona el tráfico HTTP, PostgreSQL impone aislamiento de tenant a nivel de fila, y Redis actúa como sistema nervioso central para denylist de sesiones, caché y streaming de eventos asíncronos. Los workers de Celery descargan tareas pesadas como escaneos Nmap y enriquecimiento LLM en redes Docker aisladas.

---

## Stack Tecnológico

| Tecnología | Versión |
|------------|---------|
| Python | 3.12+ |
| FastAPI | 0.115.6 |
| SQLAlchemy | 2.0.36 |
| asyncpg | 0.30.0 |
| PostgreSQL | 16 (Alpine) |
| Redis | 7 (Alpine, cliente 5.2.1) |
| Alembic | 1.14.0 |
| Celery | 5.4.0 |
| Pydantic | 2.10.4 |
| pydantic-settings | 2.7.0 |
| PyJWT[crypto] | >=2.8,<3 |
| bcrypt | >=4.0 |
| prometheus-client | >=0.26.0 |
| structlog | 24.4.0 |
| pytest | 8.3.4 |
| pytest-asyncio | 0.24.0 |
| ruff | 0.8.4 |
| mypy | 1.13.0 |
| httpx | 0.27.2 |
| fakeredis | 2.34.1 |
| Docker Compose | — |
| Groq (llama-3.3-70b) | LLM default |

---

## Estructura del Proyecto

```
soc360-pymes/
├── app/
│   ├── main.py                 # Entrypoint FastAPI, lifespan, routers
│   ├── dependencies.py         # Deps de FastAPI (get_db, get_current_user)
│   ├── event_bus.py            # EventBus Redis Streams + DLQ
│   ├── event_schemas.py        # Schemas Pydantic de eventos
│   ├── core/                   # Capa compartida
│   │   ├── config.py           # pydantic-settings
│   │   ├── database.py         # Engine async SQLAlchemy, helper RLS
│   │   ├── security.py         # JWT, bcrypt, denylist, JTI, roles
│   │   ├── redis.py            # Pool Redis + health check
│   │   ├── middleware.py       # SecurityHeaders + redirect HTTPS
│   │   ├── exceptions.py       # Jerarquía de errores
│   │   ├── logging.py          # structlog + redacción
│   │   ├── llm.py              # Abstracción LLM multi-proveedor
│   │   ├── contracts.py        # Contratos TypedDict
│   │   ├── pii.py              # Sanitización PII
│   │   └── types.py            # Tipos custom
│   └── modules/                # Módulos de dominio
│       ├── auth/               # ✅ F1 — 984 loc
│       ├── tenants/            # ✅ F1 — 532 loc
│       ├── users/              # ✅ F1 — 620 loc
│       ├── assets/             # ✅ F2 — models (57 loc)
│       ├── scans/              # ✅ F2 — models (82 loc)
│       ├── vulnerabilities/    # ✅ F2 — models (80 loc)
│       └── reports/            # ✅ F2 — models (80 loc)
├── tests/                      # 22.738 líneas / 1.091 tests
│   ├── conftest.py             # Fixtures compartidos
│   ├── unit/                   # Fakeredis + mocks
│   ├── integration/            # DB real + Alembic
│   ├── api/                    # httpx AsyncClient
│   └── modules/                # Tests por módulo
├── migrations/                 # 3 migraciones Alembic
├── docker/                     # Volúmenes Docker
├── scripts/
│   └── seed_db.py              # Seed idempotente
├── docs/
│   └── llm-abstraction.md      # Docs de capa LLM
├── docker-compose.yml
├── pytest.ini
├── .env.example
└── AGENTS.md
```

> **Nota**: Los módulos Assets, Scans y Vulnerabilities tienen modelos implementados (F2 en progreso). Los módulos esqueleto vacíos (dashboard, alerts, anomalies, ingest) han sido eliminados.

---

## Quickstart

**Requisitos previos**: Docker, Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/)

### Con uv (recomendado)

```bash
# 1. Clonar
git clone https://github.com/Dani1lopez/soc360-pymes.git
cd soc360-pymes

# 2. Sincronizar dependencias (crea .venv automáticamente)
uv sync --extra dev

# 3. Configurar entorno
cp .env.example .env
# Editar .env si es necesario (Docker expone PostgreSQL en puerto 5433)

# 4. Iniciar servicios (PostgreSQL 16 + Redis 7)
docker compose --profile dev up -d

# 5. Esperar a que los servicios estén saludables, luego migrar
uv run alembic upgrade head

# 6. Seed de base de datos con datos demo
uv run python scripts/seed_db.py

# 7. Ejecutar tests (1.091 tests en 3 capas)
uv run pytest -v

# 8. Iniciar servidor de desarrollo
uv run uvicorn app.main:app --reload

# 9. Verificar que funciona
curl http://localhost:8000/health
```

---

## Flujo de Desarrollo

1. **Branch**: Crear branches de feature desde `develop`.
2. **Commits**: Usar [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
3. **Pull Requests**: Abrir PRs contra `develop`. Asegurar que los tests pasen y `ruff` / `mypy` estén limpios.
4. **Reviews**: Todos los PRs requieren al menos una revisión antes del merge.

---

## Testing y Calidad

La suite de tests está organizada en tres capas:

| Capa | Alcance | Comando |
|------|---------|---------|
| **Unit** | Fakeredis + mocks, sin DB | `pytest tests/unit -v` |
| **Integration** | PostgreSQL real + migraciones Alembic | `pytest tests/integration -v` |
| **API** | Ciclo HTTP completo vía `httpx.AsyncClient` | `pytest tests/api -v` |

Comandos adicionales de calidad:

```bash
# Linting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy .

# Suite completa
uv run pytest -v
```

Patrones clave de testing:
- Tests de concurrencia para advisory locks y sesiones paralelas.
- Tests fail-closed para escenarios sin Redis.
- Seeding determinístico con UUIDs fijos, 2 tenants y 5 usuarios.

---

## Visión General de la API

Los siguientes endpoints están disponibles en F1:

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/auth/login` | Autenticar y recibir JWT + cookie refresh |
| `POST` | `/api/v1/auth/refresh` | Rotar refresh token (requiere cookie HttpOnly) |
| `POST` | `/api/v1/auth/logout` | Revocar sesión actual |
| `POST` | `/api/v1/auth/change-password` | Cambiar contraseña y revocar en cascada |
| `GET` | `/api/v1/users/me` | Obtener perfil del usuario actual |
| `POST` | `/api/v1/users/` | Crear usuario (admin+) |
| `GET` | `/api/v1/users/` | Listar usuarios (scoped a tenant) |
| `GET` | `/api/v1/users/{id}` | Obtener usuario por ID |
| `PATCH` | `/api/v1/users/{id}` | Actualizar usuario |
| `DELETE` | `/api/v1/users/{id}` | Desactivar usuario (autoprotegido) |
| `POST` | `/api/v1/tenants/` | Crear tenant (superadmin) |
| `GET` | `/api/v1/tenants/` | Listar tenants (superadmin) |
| `GET` | `/api/v1/tenants/{id}` | Obtener tenant por ID |
| `PATCH` | `/api/v1/tenants/{id}` | Actualizar tenant |
| `DELETE` | `/api/v1/tenants/{id}` | Desactivar tenant |

La documentación OpenAPI completa está disponible en `/api/docs` cuando el servidor está corriendo (deshabilitado en producción).

---

## Flujo de Autenticación

```mermaid
sequenceDiagram
    participant C as Client
    participant API as FastAPI
    participant DB as PostgreSQL
    participant R as Redis

    C->>API: POST /api/v1/auth/login
    API->>R: Check healthy (fail-closed)
    API->>R: Check lockout
    API->>DB: Verify credentials
    API->>DB: Check tenant active
    API->>R: Clear login attempts
    API->>API: Create JWT + refresh
    API->>R: Track JTI (denylist)
    API->>DB: Store refresh hash
    API->>C: access_token + HttpOnly cookie
```

---

## Pipeline F2 (Planificado)

```mermaid
graph LR
    A["Asset Scan Triggered"] --> B["Nmap Executor<br/>(dockerized, no shell)"]
    B --> C["XML Parser<br/>(defusedxml)"]
    C --> D["AI Enrichment<br/>(8 tasks via LLM)"]
    D --> E["Dedup<br/>(SHA-256 fingerprint)"]
    E --> F["Persist<br/>(RLS-enforced)"]
```

El pipeline F2 automatizará el descubrimiento de vulnerabilidades: un escaneo de activo dispara una ejecución containerizada de Nmap, los resultados se parsean de forma segura, se enriquecen con un LLM en 8 tareas paralelas, se deduplican vía fingerprints SHA-256, y finalmente se persisten bajo Row-Level Security.

---

## Roadmap

| Fase | Enfoque | Estado |
|------|---------|--------|
| F0 | Arquitectura y Modelo de Datos | ✅ Completado |
| F1 | Base del Backend (Auth, Tenants, Users, RLS, Events, LLM) | ✅ Completado |
| F2 | Agente de Vulnerabilidades (Nmap, LangGraph, Asset/Vuln CRUD, Dashboard, PDF) | 🔄 En Progreso |
| F3 | Tiempo Real (WebSockets, Ingestión, Anomalías) | 📋 Planificado |
| F4 | Frontend (React 18 + TS + Vite) | 📋 Planificado |
| F5 | Agentes Extra (Cumplimiento, Inteligencia) | 📋 Planificado |
| F6 | Avanzado (Email, Reportes PDF, Redis TLS) | 📋 Planificado |
| F7 | QA + Prod (E2E, CI/CD, Deploy) | 📋 Planificado |

> Los requisitos completos del producto y el plan de entregas por fase están documentados en el [PRD v1 MVP Junio](openspec/changes/prd-v1-mvp-junio/).

---

## Contribuciones

Las contribuciones son bienvenidas. Por favor abre un issue para discutir cambios significativos antes de enviar un PR. Para correcciones de bugs y mejoras pequeñas, siéntete libre de abrir un PR directamente.

- [Abrir un issue](https://github.com/Dani1lopez/soc360-pymes/issues)
- [Enviar un PR](https://github.com/Dani1lopez/soc360-pymes/pulls)

---

## Licencia

Este proyecto es **open source** bajo la [Licencia MIT](LICENSE).

```
MIT License — Copyright (c) 2026 Daniel Alcaraz López
Se concede permiso, de forma gratuita, a cualquier persona que obtenga una copia
de este software y de los archivos de documentación asociados (el "Software"),
a utilizar el Software sin restricción, incluyendo sin limitación los derechos
de uso, copia, modificación, fusión, publicación, distribución, sublicencia
y/o venta de copias del Software, y a permitir a las personas a las que se les
proporcione el Software a hacer lo mismo, sujeto a las siguientes condiciones:

El aviso de copyright anterior y este aviso de permiso se incluirán en todas
las copias o partes sustanciales del Software.

EL SOFTWARE SE PROPORCIONA "TAL CUAL", SIN GARANTÍA DE NINGÚN TIPO, EXPRESA O
IMPLÍCITA, INCLUYENDO PERO NO LIMITADO A GARANTÍAS DE COMERCIABILIDAD,
IDONEIDAD PARA UN PROPÓSITO PARTICULAR Y NO INFRACCIÓN.
```

Consulta el texto completo de la licencia en [`LICENSE`](LICENSE).
