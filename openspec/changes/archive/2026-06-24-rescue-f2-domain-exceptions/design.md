# Design: Rescue F2 Domain Exceptions

## Technical Approach

Manual extraction (not `git cherry-pick`) of the F2 domain exception classes and their unit tests from `origin/feat/f2-foundation-alignment` into `main`. The diff is confirmed at +18 / +132 lines (150 total) across exactly two files — well within the 400-line review budget. No other F2 artifacts (models, migrations, services, routers, demo target) are touched.

## Architecture Decisions

| Decision | Choice | Alternative | Rationale |
|----------|--------|-------------|-----------|
| Extraction method | Manual copy of the two file diffs | `git cherry-pick` | Cherry-pick risks dragging unrelated F2 commits; manual apply guarantees only the two target paths change |
| Class placement | Append after `LLMResponseError` with `# ── F2 Domain Exceptions ──` separator | Interleave with existing domain errors | Preserves source-branch layout; keeps F2 block visually isolated for future rescues |
| Class shape | Bare `AppError` subclasses — no custom `__init__` | Add custom `__init__` with F2-specific defaults | Follows existing `TenantError` / `UserError` pattern; YAGNI — no F2-specific defaults needed yet |
| Docstring language | Spanish (`Errores del modulo X (F2).`) | English | Matches `TenantError` / `UserError` convention already on `main` |
| Test file origin | Copy verbatim from source branch | Rewrite tests | Source tests are well-structured, DB-free, and cover all success criteria; rewriting adds risk with no benefit |
| Branch base | `feat/f2-domain-exceptions` from `main` | From `develop` | `main` is declared source of truth per `cleanup-f2-branch-state` reconciliation |

## Data Flow

No data flow — this is a pure code-addition change with no runtime side effects.

```
origin/feat/f2-foundation-alignment
    │
    │  (manual extraction: 2 files only)
    ▼
feat/f2-domain-exceptions (branched from main)
    ├── app/core/exceptions.py    (+18 lines)
    └── tests/unit/test_f2_exceptions.py  (+132 lines, new file)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/core/exceptions.py` | Modify | Append 4 F2 domain exception classes (`AssetError`, `ScanError`, `VulnerabilityError`, `ReportError`) after line 63 |
| `tests/unit/test_f2_exceptions.py` | Create | DB-free unit tests: hierarchy, instantiation, default status, custom detail/status, str, no state leak |

## Interfaces / Contracts

```python
# Appended to app/core/exceptions.py after LLMResponseError

# ── F2 Domain Exceptions ───────────────────────────────────────────────

class AssetError(AppError):
    """Errores del modulo assets (F2)."""

class ScanError(AppError):
    """Errores del modulo scans (F2)."""

class VulnerabilityError(AppError):
    """Errores del modulo vulnerabilities (F2)."""

class ReportError(AppError):
    """Errores del modulo reports (F2)."""
```

All four classes inherit `AppError.__init__(detail, status_code=400)` — no new interface surface.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | F2 exception hierarchy, default/custom status codes, detail storage, str representation, no module-state leak | `pytest tests/unit/test_f2_exceptions.py -v` — 11 test methods via parametrize + individual cases |
| Regression | Full unit suite remains green | `pytest tests/unit/ -v` — confirms no import or side-effect breakage |
| Integration | N/A | No DB, no HTTP, no service layer involved |

## Migration / Rollout

No migration required. Pure additive code change — no schema, no config, no data.

## Rollback

Revert the single commit on `feat/f2-domain-exceptions`:
- `app/core/exceptions.py` returns to 63 lines (pre-change state).
- `tests/unit/test_f2_exceptions.py` is deleted.
- No data or config impact.

## Open Questions

None.
