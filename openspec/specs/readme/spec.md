# Readme Specification

## Purpose

Defines content, structure, and quality requirements for SOC360-PyMEs bilingual README files — `README.md` (English) and `README.es.md` (Spanish) — serving as the project's public GitHub entry point.

## Requirements

| ID | Priority | Summary |
|----|----------|---------|
| REQ-RDM-001 | must-have | English README with full structure |
| REQ-RDM-002 | must-have | Spanish README mirror |
| REQ-RDM-003 | must-have | Cross-language consistency |
| REQ-RDM-004 | must-have | Professional quality (zero errors) |
| REQ-RDM-005 | must-have | Developer onboarding in <10 min |

### REQ-RDM-001: English README Content Structure

The English README (`README.md`) MUST contain all sections below in order, accurately reflecting the project's current state (F1 complete, F2 in progress).

**Sections** (in order): Hero+shields.io badges → Language switcher → TOC → Why SOC360-PyMEs → Current Status (✅ F1, 🔲 F2-F7) → Core Features → Architecture (Mermaid or ASCII) → Tech Stack table → Project Structure tree → Getting Started (copy-pasteable commands) → Development Workflow → Roadmap → Contributing → License.

**Acceptance Criteria**:
- [ ] All shields.io badges render and link correctly (Python 3.12+, FastAPI, PostgreSQL 16, Redis 7, License MIT, Tests 97/97)
- [ ] Getting Started produces 97 passing tests when executed on a fresh macOS/Linux machine
- [ ] Architecture diagram shows Client → FastAPI → PostgreSQL/Redis + Celery + LangGraph agent
- [ ] Roadmap uses emoji indicators matching PRD phases: ✅ F1, 🔲 F2, 🔮 F3+

#### Scenario: Developer understands project in 60 seconds
- GIVEN a developer visits the GitHub repository
- WHEN they scroll through README.md
- THEN they can identify: project purpose, tech stack, current status, and how to run locally

#### Scenario: Quickstart produces 97 passing tests
- GIVEN a machine with Docker and Python 3.12+
- WHEN each Getting Started command is executed in sequence
- THEN `pytest` runs and reports 97 tests passed within 10 minutes

### REQ-RDM-002: Spanish README Mirror

The Spanish README (`README.es.md`) MUST mirror `README.md` in structure, badges, commands, and accuracy — with professional Spanish translation.

**Acceptance Criteria**:
- [ ] Same section order and count as README.md
- [ ] Professional Spanish (no machine-translation artifacts; technical terms preserved in English)
- [ ] Badge URLs identical to README.md; all CLI command blocks identical (language-agnostic)
- [ ] Cross-link: `📖 [Read this in English](README.md)` at top of README.es.md
- [ ] README.md has reciprocal `📖 [Leer en Español](README.es.md)` link

#### Scenario: Spanish speaker navigates and gets equivalent information
- GIVEN a Spanish-speaking developer opens README.es.md
- WHEN they read any section
- THEN the technical content, status, and instructions match README.md exactly, expressed in natural Spanish

#### Scenario: Language switcher works bidirectionally
- GIVEN a user on README.es.md
- WHEN they click "Read this in English"
- THEN they navigate to README.md, which shows "Leer en Español" linking back

### REQ-RDM-003: Cross-Language Consistency

Both README files MUST remain structurally identical and reflect the SAME project state.

**Acceptance Criteria**:
- [ ] Section headings count matches between files (script-verifiable via `grep "^##"`)
- [ ] All shields.io badge URLs are byte-identical across both files
- [ ] Roadmap phase status indicators match (✅ F1, 🔲 F2, 🔮 F3+)
- [ ] Tech stack version numbers identical (not translated)
- [ ] Command blocks byte-identical (CLI is language-agnostic)

#### Scenario: Automated structural parity check passes
- GIVEN both README files in repo root
- WHEN section headings are extracted and compared
- THEN counts match; any structural divergence is flagged

### REQ-RDM-004: Professional Quality Standards

Both READMEs MUST pass automated quality checks with zero errors.

**Acceptance Criteria**:
- [ ] Zero markdown lint errors (valid links, no broken anchors, alt text present)
- [ ] Zero spelling/grammar errors (automated spell check, English and Spanish)
- [ ] All external URLs return HTTP 200
- [ ] TOC anchor links navigate to correct sections (GitHub-flavored markdown)
- [ ] Code blocks specify correct language for syntax highlighting
- [ ] No absolute file paths; all links relative

#### Scenario: Markdown linter passes with zero errors
- GIVEN README.md and README.es.md
- WHEN a markdown linter runs against both
- THEN zero errors or warnings are reported

### REQ-RDM-005: Developer Onboarding in Under 10 Minutes

A new developer following Getting Started MUST clone, configure, and run all tests in under 10 minutes.

**Acceptance Criteria**:
- [ ] Prerequisites listed explicitly (Docker, Python 3.12+, git)
- [ ] `.env.example` referenced as `.env` template — no manual config file edits
- [ ] Docker compose starts PostgreSQL 16 + Redis 7 with health checks
- [ ] Commands provided in order: clone → .env → Docker → venv → dependencies → migrations → seed → tests → dev server
- [ ] Dev server command (`uvicorn`) shown with default port; health endpoint (`GET /health`) documented
- [ ] No external API keys required for basic setup (Groq key optional)

#### Scenario: Fresh clone → passing tests in under 10 minutes
- GIVEN Docker and Python 3.12+ installed
- WHEN each Getting Started command block is executed in order
- THEN all 97 tests pass within 10 minutes AND server responds to `GET /health`
