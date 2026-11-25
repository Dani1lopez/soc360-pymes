# ADR: Scan graph orchestration with LangGraph

## Status

Accepted, 2026-10-08.

## Context

PRD v2 lists a LangGraph agent pipeline as a success criterion, and the archived
PRD v1 design had already named five nodes — `node_scan → node_parse →
node_enrich → node_dedup → node_persist` over a `ScanState` TypedDict — in a
file that never existed. The contracts were written and then never imported:
`app/core/contracts.py` had no consumers, its `fingerprint()` (ADR-009) had no
caller, and no service ever implemented the `upsert_findings()` that
`UpsertVulnerabilitiesResult` documented.

Meanwhile the pipeline was already implemented imperatively inside
`app/modules/scans/executor.py`, and F2 Slice 8 had already solved enrichment
without LangGraph: one `enrichment.vulnerability` Celery task per
vulnerability, with per-function persistence, its own queue, a call budget and
bounded retries.

The decisions are recorded in `odd/tasks/f2-slice-9-langgraph.md` (D1–D7); D7 is
the cost analysis that produced the option below.

## Decision

### Four nodes, and enrichment is deliberately not one of them

The graph is `scan → parse → dedup → persist`:

- `scan` runs Nmap once per address family and keeps one document per run.
- `parse` parses with defusedxml and extracts findings as data.
- `dedup` drops the findings that repeat inside this scan.
- `persist` writes the survivors through `upsert_findings` and only flushes.

`node_enrich` from the PRD v1 design is **not** implemented. Enrichment keeps a
single owner, the Slice 8 task: two orchestrators would duplicate retries and
the 120-second budget, and would reintroduce the concurrent-write overlap that
produced two review advisories in Slice 8. The graph therefore covers the scan
pipeline and hands off; it does not own generated content.

### The executor keeps the state machine

`build_scan_graph` is called from `execute_scan`, which keeps the
`running`/`completed`/`failed`/`cancelled` transitions, the single commit at the
end, the rollback on failure and the shielded cleanup that survives
cancellation. Nodes never commit, which is what preserves the pre-existing
atomicity: a cancelled or failed scan stores no findings.

`_load_scan` also stays in the executor, so a missing asset never starts a
graph. A node reports failure by writing `error` with the same reason codes the
executor used to pass as `failure_reason` (`target_not_global`, `timeout`,
`malformed_xml`, `scan_type_mismatch`), and the conditional edges stop the graph
early.

`run_agent_safely` is the boundary: it returns the final state and never raises
an ordinary failure — an unexpected exception is logged and returned as
`error="internal_error"`. `asyncio.CancelledError` is the exception, and it
needs care: LangGraph converts a node's `CancelledError` into
`langgraph.errors.NodeCancelledError`, which would otherwise be swallowed as an
internal error and leave a cancelled scan marked `failed`. The runner unwraps it
back to `CancelledError` so the executor still runs its shielded `cancelled`
transition and the live Nmap process is still terminated.

### Runtime: one pinned dependency, no checkpointer, no new queue

`langgraph==1.2.14` is pinned like the rest of `pyproject.toml`. The lock gains
23 transitive packages and the resolver changes nothing else: no existing pin
moves, and LangGraph's `httpx2` is a separate distribution from the project's
`httpx==0.27.2`.

The graph runs inside the existing `scans.wake` Celery task, on the existing
`scans` queue. There is no checkpointer: the state is transient, and the
persistence that matters is the `scans` and `vulnerabilities` rows. Retries are
the executor's existing behaviour (a failure transitions the scan to `failed`);
the graph adds no retry layer. No new feature flag either —
`SCAN_EXECUTION_ENABLED` already gates execution.

### Intra-scan dedup, and the identity question left open

`vulnerabilities.scan_id` is `NOT NULL` and there is no fingerprint column or
business unique constraint, so a vulnerability is scan-scoped today.
`fingerprint()` (ADR-009) was built for cross-scan identity but never consumed;
it was deleted with `app/core/contracts.py` rather than kept as dead code, and
returns when cross-scan identity is designed (tracked in `BACKLOG.md`).

`upsert_findings` is therefore idempotent **inside one scan**: identity comes
from the metadata that describes the observed surface (script id, host, port,
protocol, CVE), with the title as fallback when the metadata carries none, and
the function also skips identities already stored for that scan. `updated` stays
0 because nothing is ever updated in place.

`persist_node` re-applies the RLS tenant context instead of trusting the
caller's: the setting is transaction-local, so a commit anywhere in the run
expires it and the row-level policy would reject the insert.

### Contract placement

`app/core/contracts.py` is gone. `ScanState` lives in `app/agents/state.py` and
`UpsertVulnerabilitiesResult` beside its producer in
`app/modules/vulnerabilities/service.py`, so no domain module imports from
`app/agents`. The duplicate severity/status literals were removed — the
canonical ones are in `app/event_schemas.py`, and the copy in `contracts.py` was
already in drift (`acknowledged`/`resolved` against the model's `fixed`).

## Consequences

- The pipeline is four named, separately testable nodes, and the scan state
  machine is untouched: the 34 pre-existing executor/worker tests still pin it.
- Findings are deduplicated inside a scan. Cross-scan identity, and with it the
  ADR-009 fingerprint, remains undefined and is its own slice.
- Findings inserted by `upsert_findings` publish no `vulnerability.created`
  event, exactly as the previous direct insert did. The gap is now visible in
  one function and tracked in `BACKLOG.md`.
- The graph earns its dependency only through orchestration value; the
  functional fix it carries (dedup) does not require LangGraph. The cost
  analysis in `odd/tasks/f2-slice-9-langgraph.md` records both sides.
- Cancellation correctness now depends on one LangGraph error class
  (`NodeCancelledError`). It is covered by a test that fails loudly if a future
  LangGraph version changes that behaviour.

## Alternatives considered

- **Five nodes including `node_enrich`:** matches the PRD v1 design but creates
  two owners of enrichment, duplicating retries and the call budget. Rejected.
- **A graph over enrichment only:** cheaper by roughly half the code and no
  executor changes, but leaves `ScanState`, `scan`, `parse` and `dedup` unused,
  does not close the PRD criterion and still pays the dependency. Rejected.
- **No LangGraph at all (dedup and contract cleanup only):** two to four hours
  instead of a slice, and it fixes the real defect (duplicate findings), but
  leaves F2 without its last criterion and the roadmap without that learning
  goal. Rejected by explicit decision, not by necessity.
- **A checkpointer for resumable runs:** the scan row already records terminal
  state and the executor owns retry semantics; a durable graph state would add a
  second source of truth for a pipeline that runs once per claimed scan.
- **Reusing `EnrichedFinding` as the node payload:** the Slice 8 enrichment
  never consumed it and its shape (`ai_enriched`, `needs_ai_retry`) belongs to
  generated content, not to scanned findings. The graph carries the extracted
  draft shape instead.
