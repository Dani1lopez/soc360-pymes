# Design: PRD v1 MVP Junio

## Technical Approach

Extend the existing F1 auth/tenants/RLS backend with 4 new modules (assets, scans, vulnerabilities) + 2 read modules (dashboard, reports), a Celery worker pipeline (nmap + LangGraph enrichment), and a React frontend. All new tables use RLS following the existing pattern. Celery tasks wrap async code with `asyncio.run()`. LLM enrichment uses the existing `get_llm_provider()` + `llm_safe_complete()`.

## Architecture Overview

```
┌─────────────┐   ┌──────────────┐   ┌───────────────┐
│  Frontend   │──▶│  FastAPI app  │──▶│  PostgreSQL   │
│  (Vite/React)│   │  (uvicorn)    │   │  (RLS per tenant)
└─────────────┘   └──────┬───────┘   └───────────────┘
                         │
                    ┌────┴────┐
                    │  Redis  │
                    └────┬────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼─────┐   ┌─────▼──────┐   ┌─────▼──────┐
   │  Celery  │   │  Celery    │   │  Celery    │
   │  Worker  │   │  Beat      │   │  EventBus  │
   │(nmap+LLM)│   │(scheduler) │   │ (consumer) │
   └────┬─────┘   └────────────┘   └────────────┘
        │
   ┌────▼─────┐
   │vulnerable│
   │  target  │  (isolated Docker net)
   └──────────┘
```

## Data Model

### assets
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK, default gen_random_uuid() |
| tenant_id | UUID | FK tenants(id) CASCADE, NOT NULL |
| type | VARCHAR(20) | CHECK IN ('ip','domain') |
| value | VARCHAR(500) | NOT NULL |
| label | VARCHAR(255) | NULL |
| status | VARCHAR(20) | DEFAULT 'active' |
| scan_schedule | VARCHAR(100) | NULL (cron string) |
| max_scan_timeout_seconds | INTEGER | DEFAULT 300 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() |

Unique index on (tenant_id, value). RLS: superadmin OR own tenant.

### scans
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| asset_id | UUID | FK assets(id) CASCADE |
| tenant_id | UUID | FK tenants(id) CASCADE |
| status | VARCHAR(20) | CHECK IN ('pending','running','completed','failed') |
| nmap_xml_raw | TEXT | NULL |
| started_at | TIMESTAMPTZ | NULL |
| completed_at | TIMESTAMPTZ | NULL |
| error_message | TEXT | NULL |
| triggered_by | VARCHAR(20) | CHECK IN ('manual','scheduled') |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### vulnerabilities
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| asset_id | UUID | FK assets(id) CASCADE |
| scan_id | UUID | FK scans(id) SET NULL |
| tenant_id | UUID | FK tenants(id) CASCADE |
| vuln_type | VARCHAR(100) | NOT NULL |
| severity | VARCHAR(20) | NOT NULL, CHECK IN ('critical','high','medium','low','info') |
| title | VARCHAR(500) | NOT NULL |
| description | TEXT | NOT NULL |
| evidence | TEXT | DEFAULT '' |
| remediation | TEXT | DEFAULT '' |
| port | INTEGER | NULL, CHECK (0 < port <= 65535) |
| protocol | VARCHAR(20) | NULL |
| service | VARCHAR(100) | NULL |
| cve | VARCHAR(50) | NULL |
| cwe | VARCHAR(50) | NULL |
| path | VARCHAR(500) | NULL |
| cvss_score | REAL | NULL, CHECK (0.0 <= cvss_score <= 10.0) |
| ai_enriched | BOOLEAN | DEFAULT FALSE |
| needs_ai_retry | BOOLEAN | DEFAULT FALSE |
| status | VARCHAR(20) | DEFAULT 'open' |
| fingerprint | VARCHAR(64) | NOT NULL, UNIQUE |
| executive_summary | TEXT | DEFAULT '' |
| remediation_steps | JSONB | DEFAULT '[]' |
| detected_at | TIMESTAMPTZ | DEFAULT NOW() |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() |

### reports
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| tenant_id | UUID | FK tenants(id) CASCADE |
| report_type | VARCHAR(20) | CHECK IN ('asset','global','scan') |
| format | VARCHAR(20) | CHECK IN ('technical','executive','both') |
| status | VARCHAR(20) | DEFAULT 'generating' |
| file_path | VARCHAR(500) | NULL |
| asset_id | UUID | FK assets(id) SET NULL |
| scan_id | UUID | FK scans(id) SET NULL |
| generated_at | TIMESTAMPTZ | NULL |
| expires_at | TIMESTAMPTZ | NULL |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### Tenant additions (new columns)
- `scans_per_day` INTEGER DEFAULT 10
- `ai_enrichment_level` VARCHAR(20) DEFAULT 'basic', CHECK IN ('basic','premium')
- `report_types` VARCHAR[] DEFAULT '{technical,executive}'

## API Routes

All routes under `/api/v1`:

### Assets
- POST /assets — Create (admin+), plan limit check
- GET /assets — List (viewer+), paginated, filterable
- GET /assets/{id} — Detail (viewer+)
- PATCH /assets/{id} — Update (admin+)
- DELETE /assets/{id} — Soft-delete/status=inactive (admin+)
- POST /assets/{id}/scans — Trigger scan (analyst+), quota check

### Scans
- GET /scans — List (viewer+), filterable by status/asset
- GET /scans/{id} — Detail (viewer+)

### Vulnerabilities
- GET /vulnerabilities — List (viewer+), filterable by severity/status/asset/date
- GET /vulnerabilities/{id} — Detail (viewer+)
- PATCH /vulnerabilities/{id} — Status transition only (analyst+)

### Dashboard
- GET /dashboard/risk-score
- GET /dashboard/active-assets
- GET /dashboard/scans-month
- GET /dashboard/vulns-by-severity
- GET /dashboard/top-vulnerable-assets
- GET /dashboard/vuln-trend
- GET /dashboard/last-scans
- GET /dashboard/top-ports
- GET /dashboard/recent-activity
- GET /dashboard/top-cves (pro+ gated)

### Reports
- POST /reports — Request generation (admin+), async
- GET /reports — List (viewer+)
- GET /reports/{id}/download — Download PDF (admin+)

## Key Architecture Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Nmap binary in worker container | Simplest for MVP; avoids Docker-in-Docker |
| 2 | ReportLab for PDFs | No HTML→PDF (SSRF risk), pure Python |
| 3 | Celery + asyncio.run() | Beat for scheduling; avoids sync/async mix |
| 4 | Local filesystem for report storage | MVP simplicity; S3 deferred |
| 5 | SHA-256 fingerprint dedup | ADR-009 already in contracts; deterministic |
| 6 | Redis 5min cache for dashboard | Balances freshness vs DB load |
| 7 | Plan limits as tenant columns | Existing pattern in F1; simpler queries |
| 8 | Vulnerable target on isolated network | Security: known CVEs must not expose to host |

## Nmap Executor

```python
# app/agents/nmap_executor.py
def run_nmap_scan(target: str, timeout: int) -> str:
    subprocess.run(["nmap", "-sV", "-oX", "-", target],
                   capture_output=True, timeout=timeout + 30)
```

NEVER `shell=True`. Command as list, no string interpolation.

## AI Agent Pipeline (LangGraph)

5-node StateGraph using `ScanState` TypedDict:
```
node_scan → node_parse → node_enrich → node_dedup → node_persist
```

- **node_scan**: Nmap executor → raw XML in state
- **node_parse**: defusedxml → list of raw findings
- **node_enrich**: 8 AI tasks per finding via `get_llm_provider()` + `llm_safe_complete()` (1 retry)
- **node_dedup**: SHA-256 fingerprint → check existing DB vulns
- **node_persist**: `vulnerabilities/service.upsert_findings()`

## Frontend Architecture

- **Vite** + React 18 + TypeScript strict
- **TanStack Router**: 10 route definitions, lazy-loaded pages
- **TanStack Query**: server state (API data)
- **Zustand**: client state (auth: token/user; UI: sidebar/theme)
- **react-i18next**: Spanish locale
- **Recharts**: dashboard charts
- **TanStack Virtual**: large lists
- **WCAG 2.1 AA**: contrast ≥ 4.5:1, visible focus ring, aria-labels, keyboard navigation

### Route Map
```
/login → LoginPage
/dashboard → DashboardPage (10 metrics)
/assets → AssetListPage
/assets/:id → AssetDetailPage
/vulnerabilities → VulnerabilityListPage
/vulnerabilities/:id → VulnerabilityDetailPage
/scans → ScanListPage
/reports → ReportListPage
/users → UserManagementPage (admin only)
/settings → TenantConfigPage (admin only)
```

## Docker Infrastructure

8 services in docker-compose.yml:
- **postgres**: PostgreSQL 16 (existing)
- **redis**: Redis 7 (existing)
- **app**: FastAPI uvicorn
- **worker**: Celery worker with nmap + Python deps
- **beat**: Celery Beat scheduler
- **vulnerable-target**: Ubuntu 22.04 with vsftpd 2.3.4, old SSH, Apache 2.2.8, MySQL 5.0 (isolated network `vulnerable-net`, static IP 172.25.0.100, no host ports)
- **frontend**: Vite dev server (:5173) or nginx (production)

## ~35 new files, ~7 modified files

See `tasks.md` for complete file listing per task.
