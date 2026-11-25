# ADR: Tenant dashboard summary

## Status

Accepted, 2026-10-07.

## Context

PRD v2 (`openspec/changes/prd-v2-vertical-f2/proposal.md:194-200`) asks for
five dashboard metrics in F2: monitored assets, vulnerabilities by severity,
24 h scan coverage, a 30-day open-vs-resolved trend and the scan success rate.
The PRD gives no formulas, and before this slice nothing recorded when a
vulnerability was closed.

## Decision

`GET /api/v1/dashboard/summary` returns one `DashboardSummary` for exactly one
tenant (`app/modules/dashboard/`).

### Metrics

All windows are anchored to one database `now()`; days are cut in UTC.
Intervals are computed in Python from that value so the session time zone
cannot shift them across DST.

| Metric | Definition |
|--------|------------|
| `assets_monitored` | Assets with `status = 'active'` |
| `open_by_severity` | Open vulnerabilities per severity; all five keys always present |
| `coverage_24h` | Active assets with a `completed` scan in the last 24 h / active assets |
| `trend_30d` | 30 UTC days, zero-filled: vulnerabilities created vs closed per day |
| `scan_success_30d` | `completed / (completed + failed)` over scans finished in 30 days; cancelled excluded |

Ratios are fractions in `[0, 1]` rounded to four decimals, and `null` when the
denominator is 0: "no data" is not 0 %. Counters and the window start are
returned beside every ratio.

### Closing timestamp

`vulnerabilities.closed_at` is set when a finding leaves `open` and cleared on
reopen. Rows closed before this migration keep `NULL`; dates are not invented
from `updated_at`, so the trend under-reports closures older than the slice.

### Tenant scope and RBAC

- Allowed roles: admin, analyst, viewer, superadmin. `ingestor` is a machine
  role and is refused.
- Tenant users read their own tenant; another `tenant_id` returns 403.
- A superadmin must pass `tenant_id` (422 if missing, 404 if unknown). There
  is no cross-tenant aggregate.
- Every query filters by `tenant_id` explicitly, because the superadmin
  database context bypasses RLS.

### Cache

Redis key `dashboard:summary:{tenant_id}`, TTL 60 s, shared by all roles of
the tenant because the payload has no per-user data. There is no event
invalidation: scan completion emits no event, so data may be up to 60 s
stale. The cache is best-effort: Redis errors and unreadable entries fall
back to the database.

### Indexes

Tenant-first composites back the aggregations (migration `9e7a3b6c1f85`):
vulnerabilities `(tenant_id, status, severity)`, `(tenant_id, created_at)`,
partial `(tenant_id, closed_at) WHERE closed_at IS NOT NULL`, and scans
`(tenant_id, completed_at)`. Assets need none beyond `tenant_id`, because plan
limits bound assets per tenant.

## Consequences

- The success rate counts every failure reason, including infrastructure
  failures; the operator view belongs elsewhere (see `BACKLOG.md`).
- A platform-wide superadmin view is out of scope (see `BACKLOG.md`).
- Index usage is covered by definition tests only; query plans have not been
  measured on realistic data.
