# Tasks: Create Bilingual README

## Phase 1: Preparation

- [ ] 1.1 Verify no existing README.md or README.es.md in repo root
- [ ] 1.2 Review `requirements.txt` and `requirements-dev.txt` to confirm exact dependency versions for badge table
- [ ] 1.3 Review `scripts/seed_db.py` to confirm correct invocation command for quickstart step 7

## Phase 2: README.md (English — canonical)

- [ ] 2.1 Write Section 1 (Header): H1 title "SOC360-PyMEs", one-line value prop, shields.io badges (Python 3.12+, FastAPI 0.115.6, PostgreSQL 16, Redis 7, MIT, Tests 311)
- [ ] 2.2 Write Section 2 (Language Switcher): centered `🇺🇸 English | 🇪🇸 [Español](README.es.md)`
- [ ] 2.3 Write Section 3 (TOC): anchor links to all 16 H2 sections
- [ ] 2.4 Write Section 4 (Why SOC360-PyMEs): problem → solution narrative (2 paragraphs), PyME gap + multi-tenant security + LLM abstraction + event-driven architecture
- [ ] 2.5 Write Section 5 (Current Status): table with F1 ✅ complete, F2 🔄 in progress, F3–F7 📋 planned
- [ ] 2.6 Write Section 6 (Core Features): bulleted list covering auth (JWT, refresh rotation, denylist, session cap, rate limiting), multi-tenant (RLS, superadmin, tenant CRUD), RBAC, PII sanitization, 8-provider LLM abstraction, Redis Streams EventBus, 3-layer test suite
- [ ] 2.7 Write Section 7 (High-Level Architecture): Mermaid diagram (Client → FastAPI → PostgreSQL / Redis / Celery / LLM Agent)
- [ ] 2.8 Write Section 8 (Tech Stack): markdown table with category, technology, version — Python 3.12+, FastAPI 0.115.6, SQLAlchemy 2.0.36, asyncpg 0.30.0, PostgreSQL 16 Alpine, Redis 7 Alpine, Celery 5.4.0, Alembic 1.14.0, Pydantic 2.10.4, python-jose 3.3.0, passlib[bcrypt] 1.7.4, pytest 8.3.4, pytest-asyncio 0.24.0, ruff 0.8.4, mypy 1.13.0, structlog 24.4.0, Groq llama-3.3-70b
- [ ] 2.9 Write Section 9 (Project Structure): tree output of `app/` and `tests/` directories with brief descriptions
- [ ] 2.10 Write Section 10 (Quickstart): numbered step-by-step commands — clone → .env → Docker → venv → deps → migrations → seed → pytest → uvicorn → health check (11 steps with timing estimates)
- [ ] 2.11 Write Section 11 (Development Workflow): branch naming convention, PR process, test commands (pytest -v, pytest tests/unit, pytest tests/integration)
- [ ] 2.12 Write Section 12 (Testing & Quality): unit/integration/API layers, markers, coverage note, fakeredis, test count 311+
- [ ] 2.13 Write Section 13 (API Overview): key endpoints summary (POST /api/v1/auth/login, POST /api/v1/auth/refresh, POST /api/v1/auth/logout, GET /api/v1/users/me, tenant CRUD, scan endpoints)
- [ ] 2.14 Write Section 14 (Auth Flow): Mermaid sequence diagram (login → JWT → denylist check → refresh rotation)
- [ ] 2.15 Write Section 15 (F2 Pipeline): Mermaid diagram (Asset → Scan Task → Nmap Docker → Parse → LLM Agent → CVSS/CVE → Deduplicate → Persist → Redis Stream → Dashboard Update)
- [ ] 2.16 Write Section 16 (Roadmap): table F1→F2→F3→F4→F5→F6→F7 with target dates (June MVP), emoji status (✅ 🔄 📋 🔮), 1-line description per phase
- [ ] 2.17 Write Section 17 (Contributing): brief guide + note about future CONTRIBUTING.md
- [ ] 2.18 Write Section 18 (License): MIT License statement + link to LICENSE file

## Phase 3: README.es.md (Spanish — mirror)

- [ ] 3.1 Write Header (mirrors Section 1 of README.md): H1, value prop, same shields.io badge URLs
- [ ] 3.2 Write Language Switcher: `🇺🇸 [Read in English](README.md) | 🇪🇸 Español`
- [ ] 3.3 Write Sections 3–18 (TOC through License): translate each section content to natural Rioplatense Spanish, preserve all English technical terms (JWT, denylist, Redis Streams, LLM provider, etc.), keep all badge URLs and CLI commands byte-identical
- [ ] 3.4 Verify cross-links: README.es.md → README.md link at top; README.md → README.es.md link in Section 2

## Phase 4: Validation Script

- [ ] 4.1 Create `scripts/check_readme_parity.sh`: count `^##` headings in both files, assert equality
- [ ] 4.2 Extend script: extract shields.io badge URLs from both files, assert byte-identical sets
- [ ] 4.3 Extend script: extract all ` ```bash ` code blocks from both files, assert byte-identical
- [ ] 4.4 Make script executable (`chmod +x`)

## Phase 5: Verification

- [ ] 5.1 Run `scripts/check_readme_parity.sh` — assert zero diffs
- [ ] 5.2 Check all external URLs return HTTP 200 (shields.io, GitHub links)
- [ ] 5.3 Verify TOC anchor links navigate to correct H2 sections
- [ ] 5.4 Run `markdownlint` against both files (or manual validation of valid markdown)
- [ ] 5.5 Verify no absolute file paths, all links relative
- [ ] 5.6 Confirm quickstart commands reference correct files (seed_db.py invocation, alembic upgrade head, uvicorn app.main:app --reload)