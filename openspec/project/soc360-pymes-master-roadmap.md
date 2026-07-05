---
# OpenSpec Project-Level Planning Document
project: soc360-pymes
title: SOC360-PyMEs Master Roadmap and Learning Goals
type: planning
status: active
created: 2026-06-23
artifact_store: hybrid
---

# SOC360-PyMEs Master Roadmap and Learning Goals

## 1. Product Vision

SOC360-PyMEs is a cybersecurity platform for small and medium enterprises (PyMEs). It provides:

- Multi-tenant organizations (tenants)
- Users and roles
- Digital asset inventory
- Security scans
- Vulnerability tracking
- AI enrichment of findings
- Reports
- Dashboard
- End-to-end demo and reproducible deployment

## 2. Personal/Educational Objective

The primary goal is to **learn properly, not rush**. The project is built on fundamentals before frameworks:

- Backend architecture
- Tests
- Migrations
- Security
- Clean architecture
- Then frontend and deployment

### Core Rule

> Do not advance fast at the cost of structural debt.
>
> First clean, then heal, then build vertically.

## 3. Technical Objectives

- Robust FastAPI API
- Serious multi-tenant isolation
- PostgreSQL migrations with Alembic
- Reliable tests
- Real security:
  - Authentication and authorization
  - Roles
  - Rate limiting
  - Secure cookies
  - CSRF protection
  - Password policy
- Vertical F2 construction:
  - model → schema → service → router → tests
- Avoid incomplete horizontal code
- Understand old code before reuse
- AI as support, not replacement
- Usable frontend
- Reproducible Docker Compose deployment

## 4. Learning Goals

- Git recovery
- pytest and FastAPI testing
- Alembic migrations
- Backend security
- Advanced SQLAlchemy
- Multi-tenancy
- Safe Nmap and subprocess usage
- Redis and Celery
- LLM providers
- LangGraph
- ReportLab PDF generation
- React + TypeScript + TanStack

## 5. Current State

### F1 Status

F1 is approximately **85/100** but not closed.

Strong areas:

- Authentication
- Refresh tokens
- Logout
- Session revocation
- Roles
- Multi-tenant structure
- Plans
- Rate limiting
- Enumeration protection
- Lockout
- Secure cookies
- Row-level security (RLS)
- Tests

Known issues to resolve before closing F1:

- Destructive migration removed custom indexes `ix_users_email_lower` and `ix_users_tenant_active`
- `last_login_at` column is not updated on login
- Empty API tests
- Dead `request_headers` parameter in login
- Weak assertions that accept 400/401 indiscriminately

### F2 Status

Real F2 progress is around **10%**.

Useful scattered code exists:

- Models: `Asset`, `Scan`, `Vulnerability`, `Report`
- Consolidated migration
- Unit and integration tests
- F2 exceptions
- Tenant plan changes: `scans_per_day`, `ai_enrichment_level`, `report_types`

Missing:

- Services
- Routers
- Mounted APIs
- Celery and Beat
- Nmap integration
- Dashboard
- PDF reports
- LangGraph
- Vulnerability AI enrichment
- Full plan enforcement
- End-to-end scan flow

### Frontend

Frontend does not exist yet.

Future stack:

- React
- TypeScript
- Vite
- TanStack Query and Router
- Zustand
- i18n
- WCAG 2.1 AA

Planned pages:

- Login
- Dashboard
- Assets
- Vulnerabilities
- Scans
- Reports
- User Management
- Tenant Config

The human writes and understands the frontend. AI guides, reviews, and explains.

## 6. Roadmap

### Phase 0: Cleanup and Verification

- Clean branches
- Archive obsolete branches
- Backup tags before deletion
- Quarantine old F2 as reference
- Do not merge old F2 directly into `develop`
- Snapshot tests, migrations, branch graph, and `develop` state

**Output:** clean `develop`, one active branch as source of truth, old F2 tagged and referenced, baseline documented, reduced mental noise.

### Phase 1: Heal F1

- Restore removed indexes
- Fix DB-free unit tests
- Update `last_login_at` on login
- Review rate limiting
- Review CSRF
- Harden password policy
- Remove dead imports and tests

Close F1 only with:

- Green tests
- Reviewed migrations
- Correct login behavior
- Real API coverage
- No known critical debt

### Phase 2: Vertical F2

Order of construction:

1. Nmap spike
2. Assets
3. Scans
4. Vulnerabilities
5. Celery + Beat
6. Dashboard
7. LLM enrichment
8. LangGraph
9. Reports
10. Plan hardening
11. Router audit

Each module requires:

- Study and spike
- Specification
- Design
- Tasks
- Apply
- Tests
- Verify
- Archive

Build vertical complete slices. Do not abandon horizontal layers.

#### Assets Goals

- Create, list, update, deactivate, and delete as applicable
- Tenant ownership
- Plan limits
- Scan relationship

#### Scans Goals

- Create scan
- Execute or simulate
- Persist state, timestamps, and errors
- Asset and tenant relation
- Celery + Nmap preparation

#### Vulnerabilities Goals

- Persist findings
- Severity and CVSS
- Deduplication
- Tenant isolation
- AI enrichment preparation

#### Celery + Beat Goals

- Async scans
- Scheduled scans
- Avoid blocking the API
- Errors and retries
- Redis configured correctly

#### Dashboard Goals

- Total assets
- Vulnerabilities by severity
- Recent scans
- Trends
- Tenant status
- Frontend-ready data

#### LLM Enrichment Goals

- Provider abstraction
- Mock provider tests
- No hard coupling to a single provider
- Avoid unnecessary sensitive data exposure
- Explanations for non-expert users

#### LangGraph Goals

- Analysis workflows and agents only after understanding
- Isolated and testable design

#### Reports Goals

- Tenant, asset, and scan reports
- Spanish PDF output
- Executive summary
- Recommendations
- Technical evidence

### Phase 3: Frontend

Build 8 functional pages:

- Login connected to API
- Useful dashboard
- Assets management
- Scans management
- Vulnerabilities management
- Visible reports
- User Management
- Tenant Config

Build slowly. Avoid giant AI-generated components.

### Phase 4: Deploy

- Multi-stage API Dockerfile
- Full Docker Compose with PostgreSQL, Redis, backend, and frontend
- Clean environment variables
- Redis password
- Coherent configuration
- CI if decided
- Startup documentation

`docker compose up` should lift the system.

Do not deploy before the frontend exists.

## 7. Non-Negotiables

- No important code without proposal, spec, design, tasks, apply, verify, and archive
- No merge without verify
- Do not copy old F2 blindly
- Tenant isolation from day one:
  - `tenant_id`
  - Composite foreign keys when applicable
  - RLS
  - Cross-tenant tests
  - Router filtering
- Small slices
- Learn before producing

## 8. Main Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Burnout | Small phases and checkpoints |
| Branch chaos | Phase 0 cleanup, backups, and tags |
| Multi-tenant leaks | Tenant and RLS tests |
| Dangerous migrations | Migration audits |
| AI creating unreviewed debt | AI as assistant with explanation, diffs, tests, and specs |

## 9. Open Questions and Decisions

### OpenSpec and GitHub

The maintainer is unsure whether OpenSpec artifacts should be uploaded to GitHub. This is a pending decision. Do **not** modify `.gitignore` unless explicitly requested.
