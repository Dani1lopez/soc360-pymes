# PRD — F1 Security Closure

## Objetivo

Cerrar F1 (backend base) con garantías: autenticación sólida, configuración segura, endpoints protegidos, logs sin PII, tests de cobertura y sin issues abiertos de seguridad.

---

## ✅ Slices Completados (F1 Original)

| Slice | Issue | Qué se hizo | PR |
|-------|-------|-------------|-----|
| Gate 0 | — | Migración Alembic operativa + marker `integration` funcional | — |
| Slice 1 | #16 | Refresh token race protection: single-use via `revoked_at`, advisory lock, JTI tracking | — |
| Slice 2 | #19 | Login lockout privacy: 401 genérico para TODOS los fallos de auth | #34 |
| Slice 3 | #21/#22 | `ENVIRONMENT` sin default (fail-fast) + PostgreSQL bajo perfil `dev` | #35 |
| Slice 4 | #23 | f-string SQL → `set_config('app.current_tenant', :tenant_id, true)` parametrizado | #36 |
| Slice 5 | #24 | Swagger/ReDoc condicional (`None` en prod) + SecurityHeadersMiddleware + HTTPSRedirectMiddleware | #37 |
| Slice 6 | #25 | `UserCreate.min_length=12` + PII sanitizado (email hash, IP /24, UA truncado) + seed sin credenciales | #38 |
| Slice 7 | #5 | Tests unitarios: create_tenant, list_tenants, get_user_by_email, list_users, _get_active_tenant | #39 |

---

## 🔍 Post-F1: Hallazgos del Judgment Day

El 26/04 se ejecutó un adversarial review (2 jueces ciegos) sobre todo F1. Se encontraron **12 issues nuevos** que quedan pendientes para considerar F1 realmente cerrada.

### 🔴 Críticos

| # | Título | Prioridad |
|---|--------|-----------|
| [#40](https://github.com/Dani1lopez/soc360-pymes/issues/40) | `CurrentUserDep` no setea tenant context — RLS roto en endpoints normales | **1** |
| [#41](https://github.com/Dani1lopez/soc360-pymes/issues/41) | Test DB setup falla por permisos — suite no corre limpia | **2** |

### 🟠 Altos

| # | Título | Prioridad |
|---|--------|-----------|
| [#42](https://github.com/Dani1lopez/soc360-pymes/issues/42) | PII raw publicado a Redis antes de sanitizar | 3 |
| [#43](https://github.com/Dani1lopez/soc360-pymes/issues/43) | User-Agent nunca llega al service login — sanitización es código muerto | 4 |
| [#44](https://github.com/Dani1lopez/soc360-pymes/issues/44) | Middleware order incorrecto — HTTPSRedirect corta antes de SecurityHeaders | 5 |
| [#45](https://github.com/Dani1lopez/soc360-pymes/issues/45) | IP sanitization solo IPv4 — IPv6 produce prefijo malformado | 6 |
| [#46](https://github.com/Dani1lopez/soc360-pymes/issues/46) | `openapi_url` expuesto en producción aunque docs desactivados | 7 |
| [#47](https://github.com/Dani1lopez/soc360-pymes/issues/47) | Seed passwords hardcodeadas como fallback en texto plano | 8 |
| [#48](https://github.com/Dani1lopez/soc360-pymes/issues/48) | `X-Forwarded-Proto` spoofeable — HTTPS redirect se puede bypassear | 9 |

### 🟡 Medios

| # | Título | Prioridad |
|---|--------|-----------|
| [#49](https://github.com/Dani1lopez/soc360-pymes/issues/49) | SHA256[:16] para hash de email — 64 bits, colisiones posibles a escala | 10 |
| [#50](https://github.com/Dani1lopez/soc360-pymes/issues/50) | Cookie `max_age` del refresh token hardcodeado (no usa settings) | 11 |

### 🟢 Bajos

| # | Título | Prioridad |
|---|--------|-----------|
| [#51](https://github.com/Dani1lopez/soc360-pymes/issues/51) | Coverage tests solo chequean SQL compilado, no runtime | 12 |

---

## Estado Actual

**F1 original: COMPLETA** ✅ (8 slices, 6 PRs mergeadas)
**Post-F1 findings: 12 issues abiertas** 🔴2 🟠7 🟡2 🟢1

> F1 no se considera 100% cerrada hasta resolver los issues 🔴 y 🟠.
> Los issues 🟡 y 🟢 se pueden resolver después sin bloquear F2.

## Scope Excluido

- Issue #3 — feat(core): LLM abstraction layer (pertenece a F2)

---

*Documento generado el 2026-04-26. Última actualización: post Judgment Day.*
