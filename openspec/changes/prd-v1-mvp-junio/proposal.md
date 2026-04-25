# PRD v1 MVP Junio — Proposal

## Intent

SOC360-Pymes v1 MVP delivers a SOC-as-a-Service for PyMEs: register network assets, launch Nmap scans against a simulated vulnerable environment, AI-enrich findings into actionable vulnerabilities, and present everything through dashboards and PDF reports. It bridges the gap between F1 (auth/tenants — 100% done, 97 tests) and a demo-able product by building F2 (vulnerability agent backend) and F4 (React frontend) for a June 2026 presentation.

For the live demo, a Docker container (`vulnerable-target`) simulates a vulnerable company with deliberately exposed services (FTP backdoor, old SSH, outdated Apache, unsecured MySQL) so the scanner has real findings to detect, enrich, and report.

## Scope

### Demo Environment
- Vulnerable target container: deliberately insecure services with known CVEs (vsftpd 2.3.4 backdoor, old OpenSSH, Apache 2.2.8, MySQL 5.0) for live scan demonstrations
- Added to docker-compose.yml as separate service on internal network

### Backend (F2)
- Asset CRUD: IP, Dominio, Base de Datos types; create/read/update/delete with RLS
- Scan engine: Nmap dockerized executor, manual + programmed triggers (Celery Beat), scan lifecycle (pending→running→completed/failed)
- LangGraph agent (5 nodes): scan → parse Nmap XML → AI enrichment → dedup → persist
- AI enrichment pipeline (Groq llama-3.3-70b-versatile default): severity classification, CVE detection, Spanish descriptions, remediation steps, CVSS scoring, executive translation, prioritization, step-by-step instructions
- AI error handling: 1 auto retry → mark needs_ai_retry=true + notify user (Option C hybrid)
- Vulnerability CRUD: list/detail/status transitions (open→acknowledged→resolved/accepted_risk/false_positive)
- Dashboard API: 10 metrics (active assets, scans/month, vulns by severity, top-5 vulnerable assets, trend graph, last scan/asset, global risk score 0-100, top-10 exposed ports, recent activity, top CVEs)
- Reports API: 3 PDF types via ReportLab generated async in background (asset technical+executive, global monthly, scan report with new-vs-closed)
- Plan enforcement: 4 plans in DB (free/starter/pro/enterprise), 3 active for demo (free/pro/enterprise), limits stored as columns in tenants table (max_assets, scans_per_day, ai_enrichment_level, report_types)
- Redis Streams events: expand existing bus for scan lifecycle (scan.started, scan.completed, scan.failed, vuln.created, vuln.updated)

### Frontend (F4)
- 8 pages: Login, Dashboard (10 metrics), Assets (list+detail+create), Vulnerabilities (list+detail+status), Scans (list+manual+history), Reports (download 3 PDFs), User Management (admin CRUD), Tenant Config (plan/settings/schedule)
- React 18 + TypeScript + Vite, TanStack Query + Router
- WCAG 2.1 AA, i18n (react-i18next), auto-refresh tokens
- Virtualized lists (TanStack Virtual)

## Out of Scope
- Real-time scanning agent (F3)
- Compliance/intelligence agents (F5)
- Email notifications (F6)
- E2E tests + CI/CD pipeline (F7)
- API endpoint & Docker image scanners (F5)
- Full retry queue with 3 attempts (F5)
- White-label reports (enterprise-only, deferred)

## User Stories
1. As an admin, I register a network asset (IP) pointing to the simulated vulnerable target and launch a scan to discover vulnerabilities
2. As an admin, I schedule recurring scans per asset and review scan history
3. As an analyst, I view vulnerabilities classified by severity with AI-generated remediation steps in Spanish
4. As a viewer, I see the dashboard with risk score, top vulnerable assets, and vulnerability trends
5. As an admin, I download a PDF report (technical or executive) for a specific asset
6. As an admin, I download a global monthly report showing risk trends and top CVEs
7. As an admin, I manage users (create/edit/deactivate) within my tenant
8. As a superadmin, I view cross-tenant data and configure plans
9. As a demo presenter, I run a live scan against the vulnerable-target container and show the audience real-time vulnerability detection and AI enrichment

## Phases

### F1 — Backend Base ✅ DONE
- Auth (JWT+refresh+denylist+CSRF), RLS, tenants, users, seeds — 97/97 tests

### F2 — SOC Core Backend (build order)
1. Vulnerable target Docker container setup (deliberately insecure services)
2. Asset models + CRUD (RLS-enforced)
3. Nmap executor (dockerized, safe command builder)
4. Scan models + lifecycle (pending→running→completed/failed)
5. Celery worker + Beat setup (scan tasks, scheduled scans)
6. Vulnerability models + upsert with dedup (fingerprint ADR-009)
7. LLM enrichment node (8 AI tasks: severity/CVE/description/remediation/CVSS/executive/prioritization/steps)
8. LangGraph agent wiring (5-node pipeline)
9. Dashboard API (10 metrics)
10. Reports API (ReportLab PDFs, 3 types, async background generation)
11. Plan model + limit enforcement as tenant columns
12. Redis Streams: scan lifecycle events

### F4 — React Frontend
1. Project scaffolding (Vite+React+TS+TanStack+i18n+Zustand)
2. Auth flow (login, token refresh)
3. Dashboard page (10 metrics, charts)
4. Assets pages (list/detail/create, scan trigger)
5. Scans pages (list/history, manual launch)
6. Vulnerabilities pages (list/detail/status change)
7. Reports page (download 3 PDF types)
8. User management + Tenant config pages

## Constraints & Assumptions
- Groq llama-3.3-70b-versatile as default LLM; abstraction supports fallback providers
- Nmap runs in Docker container — no shell injection (SO-001)
- Celery workers for scan tasks use asyncio.run() — never async def
- Existing contracts (EnrichedFinding, ScanState, UpsertVulnerabilitiesResult) are canon
- Fingerprint algorithm: SHA-256(asset_id|vuln_type|port|cve|cwe|path) per ADR-009
- No HTML-based PDF generation (SSRF risk) — ReportLab only
- Single instance deploy for MVP (AWS or Hetzner VPS)
- Vulnerable target container on isolated Docker network for safe demo

## Success Criteria
- [ ] Admin can register IP/Dominio asset pointing to vulnerable-target and trigger manual Nmap scan
- [ ] Vulnerabilities appear with AI enrichment (severity, CVE, Spanish description, CVSS, remediation)
- [ ] Dashboard renders 10 real metrics from scan data
- [ ] PDF reports downloadable (asset, monthly global, scan)
- [ ] Plan limits enforced (max assets, scans/day, AI level, report types)
- [ ] All 8 frontend pages functional with WCAG 2.1 AA
- [ ] F1 tests still pass (97/97) — no regressions
- [ ] Live demo: scan vulnerable-target, detect real CVEs, show AI enrichment in dashboard

## Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| LLM enrichment latency/slowness | Med | Async pipeline, needs_ai_retry flag, deferred retry |
| Nmap scan timeout on large networks | Med | Per-asset scope limits, scan timeout config |
| Groq rate limiting | Med | Provider abstraction allows swap; MockLLMProvider for dev |
| ReportLab PDF complexity | Low | Start with simple templates; avoid dynamic HTML |
| Schedule slippage to miss June | Med | DB asset type can be cut; 12 F2 items with clear priority |
| Frontend scope creep | Med | 8 pages locked; no extra features added mid-sprint |
| Vulnerable target stability | Low | Pre-built Docker image, healthcheck, restart policy |
