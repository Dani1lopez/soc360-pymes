# ADR: Retryable vulnerability LLM enrichment

## Status

Accepted, 2026-10-08.

## Context

Scan findings need explanations, actionable remediation and business context.
F2 Slice 8 adds nine enrichment functions without extending the scan deadline
or coupling scanner evidence to generated content. The decisions are recorded
in `odd/tasks/f2-slice-8-llm-enrichment.md` (D1–D9); LangGraph orchestration
remains Slice 9 work.

## Decision

### Functions and tenant levels

`tenants.ai_enrichment_level` controls the number of functions, not the model.
A database CHECK accepts only `basic`, `standard` and `full`; there is no `none`
level. The nine function slugs are `executive_summary`,
`technical_description`, `exploitability`, `contextual_severity`, `remediation`,
`business_impact`, `references`, `mitigation_plan` and `hardening`.

| Level | Functions |
|-------|-----------|
| `basic` (3) | Executive summary, contextual severity, concrete remediation |
| `standard` (6) | Basic + technical description, exploitability, references |
| `full` (9) | Standard + business impact, prioritized mitigation plan, general hardening |

### Storage and idempotency

`vulnerability_enrichments` stores one row per `(vulnerability_id, function)`:
content, status (`pending`, `ok`, `failed`), model, prompt version, input hash,
attempts, error and timestamps. A composite foreign key to
`vulnerabilities(id, tenant_id)` prevents cross-tenant associations and cascades
on deletion. The tenant foreign key also cascades. The migration enables and
forces RLS using the standard tenant/superadmin policy.

A function is skipped only when its row is `ok` and `input_hash`,
`prompt_version` and `model` all match. The hash is SHA-256 of the raw finding
snapshot and language, serialized as canonical JSON. Per-function prompt
versions are code constants. Plan upgrades therefore generate missing functions
without regenerating unchanged successful ones.

### Prompt and citation boundary

Instructions belong to the system prompt; finding fields are untrusted data in
an explicitly delimited `<finding>` user block. Every rendered value is
sanitized and HTML-escaped, including non-string metadata converted to text.
This is a defense boundary, not a guarantee that generated prose is correct.

All nine outputs pass the same citation filter: CVE/CWE identifiers not supplied
in the finding are replaced with `[unverified reference removed]`. The
`references` function is LLM-generated; authoritative deterministic NVD/MITRE
lookup is deferred. The filter does not validate arbitrary prose or URLs.

Language is a prompt parameter, included in cache identity. Only English (`en`)
is currently supported; Spanish requires extending both the prompt language map
and the settings validator.

### Execution and delivery

The service loads the snapshot and rows before scheduling provider calls. A
semaphore bounds concurrency (default 3), and an overall call budget (default
120 seconds) includes semaphore waiting. No database I/O occurs inside the
concurrent calls; results are persisted sequentially, with commit owned by the
caller. Completed outputs survive budget expiry; unfinished functions become
`failed` with `budget_exceeded`. Failures retain previous content. A conditional
upsert prevents a late failure from downgrading an identical concurrent `ok`
row (same hash, prompt version and model).

One `enrichment.vulnerability` Celery task runs per vulnerability on the dedicated
`enrichment` queue. Soft/hard limits are budget + 30/+ 60 seconds. There are up
to three retries after the initial execution, waiting 30, 60 and 120 seconds,
for failed functions or unexpected exceptions. Each retry skips unchanged
successes; deleted vulnerabilities are ignored. The Compose enrichment worker
runs with concurrency 2, independently of the scan worker.

After a completed scan, `_wake` publishes one task per stored vulnerability,
best effort. Publishing has a three-second request deadline. There is no
periodic enrichment sweep. `ENRICHMENT_ENABLED=False` by default is a cost-safety
switch for publishing, relaunch and worker execution.

OpenRouter is an additional registered provider, using `OpenAICompatProvider`
at `https://openrouter.ai/api/v1`. Select it with `LLM_PROVIDER=openrouter`,
`OPENROUTER_API_KEY` and `OPENROUTER_MODEL` (default
`inclusionai/ling-flash-3.0:free`). The shared model resolver supplies the same
model identity to construction and persistence; the global provider default
remains Groq.

### API and tenant scope

All routes have the `/api/v1` prefix:

| Route | Behavior | Roles |
|-------|----------|-------|
| `GET /vulnerabilities/{id}/enrichment` | One item per function in the current tenant level; absent rows are `missing`; stored statuses/content remain readable when disabled | admin, analyst, viewer, superadmin |
| `POST /vulnerabilities/{id}/enrichment` | Queue a task; the task decides which functions are missing, failed or stale | admin, analyst, superadmin |
| `POST /scans/{id}/enrichment` | Queue vulnerabilities with fewer `ok` rows than the current level's function count | admin, analyst, superadmin |

`ingestor` is excluded. Tenant users access their own records; superadmins may
access other tenants, but each task receives the finding's actual tenant ID.
Invisible or unknown records return 404. POST returns 202 with queued counts
only after publishing succeeds (or when the scan has no candidates), and 503
when enrichment is disabled or publishing fails. With no periodic sweep, a
failed publish must not be advertised as accepted work.

## Consequences

- Generated content is auditable and independently retryable, but requires a
  migration and a dedicated worker. It is not authoritative scanner evidence.
- The call budget is not a token/cost quota; per-tenant cost controls remain
  follow-up work in `BACKLOG.md`.
- Scan relaunch counts `ok` rows without checking their identities, so it misses
  stale successes. A vulnerability relaunch does detect them when its task runs.
- A mid-loop scan publish failure returns 503 without the partial queued count.
  A publishing timeout does not cancel the underlying `apply_async` thread.
- Prompt hardening, deterministic references, Spanish support and remaining
  test/schema debt are tracked in `BACKLOG.md`.

## Alternatives considered

- **D1:** One JSONB row with schema-free per-function state, columns on the hot
  vulnerabilities table, or reuse of scanner metadata. Separate rows preserve
  typed status and provenance without mixing scanner and generated data.
- **D2:** One task per function increases queue traffic ninefold; one per scan
  lets a slow finding block the batch; synchronous enrichment extends the scan
  deadline. One task per vulnerability bounds work while allowing partial retry.
- **D6:** A Beat sweep adds machinery; manual-only relaunch omits automatic
  recovery. Bounded task retries plus persisted function state were selected.
- **D7:** Always run all nine and vary the model, or remove levels entirely.
  Function-count levels instead make upgrades reuse existing successes.
