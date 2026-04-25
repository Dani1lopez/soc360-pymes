# Task Breakdown — PRD v1 MVP Junio

**Total tasks**: 25 (F2: 15, F4: 10)
**Must-have**: 22 | **Nice-to-have**: 2 | **Stretch-goal**: 1

## Delivery Slices

### Slice 1 — Foundation (T-001–T-005)
DB migration + config + vulnerable target + assets CRUD + nmap executor = 5 tasks
**Value**: Admin can register assets and scan them.

### Slice 2 — Scan & Detect (T-006–T-009)
Scan lifecycle + vuln models + Celery + enrichment = 4 tasks
**Value**: Full scan→vuln pipeline with AI enrichment.

### Slice 3 — Agent & UI (T-010–T-014)
LangGraph + dashboard + reports + plan enforcement + wire = 5 tasks
**Value**: Dashboard metrics, PDF reports, plan limits.

### Slice 4 — Events (T-015)
Event schemas finalized = 1 task (stretch, can be deferred)

### Slice 5 — Frontend Shell (T-016–T-017)
Scaffold + auth = 2 tasks
**Value**: Login and navigation shell.

### Slice 6 — Frontend Pages (T-018–T-023)
6 feature pages = 6 tasks
**Value**: Full MVP user experience.

### Slice 7 — Dockerize Frontend (T-024)
Dockerfile + compose final = 1 task
**Value**: One-command full-stack deploy.

---

## F2 — SOC Core Backend (15 tasks)

### T-001: Migration — F2 tables + RLS
**Priority**: must-have | **Depends on**: none
Create: `migrations/versions/xxx_add_f2_tables.py`
Adds 4 tables (assets, scans, vulnerabilities, reports) + RLS + indexes + tenant columns.

### T-002: Config, exceptions, dependencies for F2
**Priority**: must-have | **Depends on**: none
Modify: `app/core/config.py`, `app/core/exceptions.py`, `app/dependencies.py`, `requirements.txt`
Add Celery/scan/report config, domain exceptions, RBAC aliases, new pip deps.

### T-003: Vulnerable target Docker container
**Priority**: must-have | **Depends on**: none
Create: `docker/vulnerable-target/Dockerfile`, `entrypoint.sh`, `vsftpd.conf`
Simulated vulnerable company with 4 insecure services on isolated network.

### T-004: Asset module (models + service + router + tests)
**Priority**: must-have | **Depends on**: T-001, T-002
Create: `app/modules/assets/models.py`, `schemas.py`, `service.py`, `router.py`
Full CRUD for IP/Domain assets with RLS + plan limit enforcement.

### T-005: Nmap executor
**Priority**: must-have | **Depends on**: T-002
Create: `app/agents/nmap_executor.py`
Safe subprocess.run nmap — never shell=True. Returns XML string.

### T-006: Scan module (models + service + router + tests)
**Priority**: must-have | **Depends on**: T-001, T-002, T-004
Create: `app/modules/scans/models.py`, `schemas.py`, `service.py`, `router.py`
Scan lifecycle: trigger, quota check, status tracking, event publication.

### T-007: Vulnerability module (models + service + router + tests)
**Priority**: must-have | **Depends on**: T-001, T-002, T-004
Create: `app/modules/vulnerabilities/models.py`, `schemas.py`, `service.py`, `router.py`
CRUD + SHA-256 fingerprint dedup + status transitions + RBAC.

### T-008: Celery app + scan task + Beat schedule
**Priority**: must-have | **Depends on**: T-002, T-005, T-006
Create: `app/celery_app.py`, `app/tasks/scan_tasks.py`, `app/tasks/scheduled_tasks.py`
Celery worker with Redis broker, scan execution task, Beat for scheduled scans.

### T-009: LLM enrichment pipeline (8 AI tasks)
**Priority**: must-have | **Depends on**: T-002, T-007
Create: `app/agents/enrichment.py`
8 enrichment functions: severity, CVE, description, remediation, CVSS, executive, priority, steps.

### T-010: LangGraph agent wiring (5-node pipeline)
**Priority**: must-have | **Depends on**: T-005, T-007, T-009
Create: `app/agents/vulnerability_agent.py`
5-node StateGraph: scan → parse → enrich → dedup → persist.

### T-011: Dashboard service + router (10 metrics)
**Priority**: must-have | **Depends on**: T-001, T-002, T-004, T-006, T-007
Create: `app/modules/dashboard/service.py`, `router.py`
10 metrics with SQL aggregations + Redis 5min cache + plan gating.

### T-012: Reports module (models + service + router + ReportLab PDFs)
**Priority**: must-have | **Depends on**: T-001, T-002, T-004, T-006, T-007, T-008
Create: `app/modules/reports/`, `app/reports/templates/`, `app/tasks/report_tasks.py`
Async PDF generation (3 types) via Celery + ReportLab.

### T-013: Plan limit enforcement
**Priority**: must-have | **Depends on**: T-001, T-002, T-004
Modify: `app/modules/tenants/` — add columns, quota checks, plan comparison.

### T-014: Wire routers + docker-compose full stack
**Priority**: must-have | **Depends on**: T-003, T-004, T-006, T-007, T-011, T-012, T-013
Modify: `app/main.py`, `docker-compose.yml`, `Dockerfile`
Register all routers. Full docker-compose with app, worker, beat, vulnerable-target.

### T-015: Event schemas expansion (stretch-goal)
**Priority**: stretch-goal | **Depends on**: T-002, T-006, T-007, T-014
Modify: `app/event_schemas.py`, `app/event_bus.py`
5 new event types: scan.started/completed/failed, vuln.created/updated.

---

## F4 — React Frontend (10 tasks)

### T-016: Frontend scaffolding
**Priority**: must-have | **Depends on**: T-014
Create: `frontend/` — Vite + React + TS + TanStack Query/Router + Zustand + i18n + Tailwind
Full project scaffold with route definitions, API client, auth store.

### T-017: Auth flow (login + token refresh)
**Priority**: must-have | **Depends on**: T-016
Create: `frontend/src/pages/LoginPage.tsx`, `components/AuthProvider.tsx`, `api/auth.ts`
Login form, auto token refresh, Zustand auth store, protected routes.

### T-018: Dashboard page (10 metrics, charts)
**Priority**: must-have | **Depends on**: T-016, T-017, T-011
Create: `frontend/src/pages/DashboardPage.tsx`, `components/dashboard/`
10 metric panes: risk gauge, charts (recharts), tables, 30s auto-refresh.

### T-019: Assets pages (list + detail + create + scan trigger)
**Priority**: must-have | **Depends on**: T-016, T-017, T-004
Create: `frontend/src/pages/AssetListPage.tsx`, `AssetDetailPage.tsx`, `components/assets/`
Virtualized list, type/status filters, create form, scan trigger button.

### T-020: Vulnerabilities pages (list + detail + status transition)
**Priority**: nice-to-have | **Depends on**: T-016, T-017, T-007
Create: `frontend/src/pages/VulnerabilityListPage.tsx`, `VulnerabilityDetailPage.tsx`, `components/vulnerabilities/`
Virtualized table with 4 filter dimensions, status workflow, AI enrichment display.

### T-021: Scans pages (list + history)
**Priority**: must-have | **Depends on**: T-016, T-017, T-006, T-019
Create: `frontend/src/pages/ScanListPage.tsx`, `components/scans/`
Scan history with status indicators, expandable detail rows.

### T-022: Reports page (list + generate + download)
**Priority**: nice-to-have | **Depends on**: T-016, T-017, T-012
Create: `frontend/src/pages/ReportListPage.tsx`, `components/reports/`
Report list with status badges, generate modal, download button.

### T-023: User management + Tenant config pages
**Priority**: must-have | **Depends on**: T-016, T-017
Create: `frontend/src/pages/UserManagementPage.tsx`, `TenantConfigPage.tsx`, `components/settings/`
Admin: user CRUD, plan info, schedule config, upgrade CTA.

### T-024: Frontend Dockerfile + final compose
**Priority**: must-have | **Depends on**: T-016–T-023
Create: `frontend/Dockerfile`, `frontend/nginx.conf`
Multi-stage Docker build. Full stack `docker compose up` with all 8 services.
