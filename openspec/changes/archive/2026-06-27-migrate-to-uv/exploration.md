# Exploration: migrate-to-uv

> **SDD phase:** explore
> **Change:** `migrate-to-uv`
> **Mode:** hybrid (OpenSpec + Engram)
> **Scope:** Read-only audit. No code, requirements, lockfiles, or CI changed.

## Exploration: migrate-to-uv

### Current State

The project is a FastAPI + SQLAlchemy 2 (async) + Alembic + Celery backend (Python 3.12+) with a separate worker profile. Dependency management today is **plain pip with two flat requirement files** and no project metadata:

- `requirements.txt` (28 lines) — 13 production packages, several with extras: `uvicorn[standard]`, `sqlalchemy[asyncio]`, `redis[hiredis]`, `celery[redis]`, `python-jose[cryptography]`, `passlib[bcrypt]`.
- `requirements-dev.txt` (17 lines) — starts with `-r requirements.txt`, then pytest/pytest-asyncio, ruff, mypy, anyio, httpx, fakeredis. **Note:** `httpx`, `pytest`, and `pytest-asyncio` are duplicated.
- **No `pyproject.toml`, no `setup.py`, no `setup.cfg`, no `uv.lock`, no `.python-version`** tracked in the worktree.
- **Python pin:** README and `openspec/specs/readme/spec.md` declare `Python 3.12+`; CI pins `python-version: "3.12"`.
- **Alembic:** `alembic.ini` uses `prepend_sys_path = .`; `migrations/env.py` is straightforward.
- **Docker/CI:**
  - `docker-compose.yml` runs PostgreSQL 16 and Redis 7 for the `dev` profile (no app container yet).
  - `.github/workflows/ci.yml` uses `actions/setup-python@v5` with `cache: pip` and explicit `pip install -r requirements-dev.txt`.
- **Local workflow** (bilingual README + readme spec): `python -m venv .venv` → `pip install -r requirements-dev.txt` → `pytest`. Past verify-reports consistently reference `.venv/bin/{pytest,ruff,mypy}`.
- **One existing spec is sensitive to the install command shape:** `openspec/specs/readme/spec.md` requires `clone → .env → Docker → venv → dependencies → migrations → seed → tests → dev server` as the documented order. A uv-based install can keep that order intact with a small wording change.

### Affected Areas

- `requirements.txt` — becomes either (a) deleted after migration, or (b) regenerated from `uv pip compile` as a temporary fallback.
- `requirements-dev.txt` — same as above; also the source of the duplicate-deps noise that uv resolves automatically.
- `pyproject.toml` — **new**; carries PEP 621 metadata, runtime dependencies, optional dependency groups, and tool config (ruff/mypy/pytest) once we own install.
- `uv.lock` — **new**; auto-generated, deterministic, cross-platform resolution. Not hand-edited.
- `.python-version` — **new** (1 line, e.g. `3.12`); lets `uv` pin the interpreter and matches what the F2 worktree already used.
- `.github/workflows/ci.yml` — switch to `astral-sh/setup-uv@v4`, `uv sync --frozen --extra dev`, and `uv run pytest`. Drop `cache: pip`.
- `README.md` and `README.es.md` — replace the `python -m venv` + `pip install` block with the uv equivalent in both languages. The Python 3.12+ badge stays valid.
- `openspec/specs/readme/spec.md` — wording update so the documented order is "uv (or venv) → dependencies" instead of "venv → dependencies". Small spec amendment, not a behavior change.
- `openspec/changes/prd-v1-mvp-junio/tasks.md` — the T-007 line that says "Modify … `requirements.txt`" / "new pip deps" should be re-anchored to `pyproject.toml` to stay accurate (cosmetic; PRD change is not modified in this PR).
- `scripts/seed_db.py` — **unaffected** (uses `sys.path.insert`, not venv tooling). Worth a smoke test under `uv run`.
- `tests/integration/conftest.py`, `tests/conftest.py` — **unaffected** at the install layer; any past `.venv/bin/...` invocations documented in historical verify-reports remain valid because `uv run` invokes the same venv layout.

### Approaches

1. **`uv pip` workflow (drop-in, no project metadata)** — Keep `requirements.txt` and `requirements-dev.txt` exactly as they are. Run `uv venv` to create the venv, then `uv pip install -r requirements-dev.txt` for day-to-day work. CI uses `astral-sh/setup-uv@v4` + `uv pip install --system -r requirements-dev.txt` (or a `uv venv` step). Zero change to project metadata.
   - Pros: Smallest possible diff; no spec edits; reviewers do not need to learn PEP 621 / lockfile semantics; trivially reversible.
   - Cons: No `uv.lock`, so resolution is non-deterministic across platforms; loses the `uv run` / `uv add` ergonomic wins; still carries the duplicate-deps noise in `requirements-dev.txt`; doesn't match how most of the uv ecosystem is moving (project-mode).
   - Effort: **Low** (≈40–80 changed lines, dominated by README).

2. **Full project-mode migration (`pyproject.toml` + `uv.lock`)** — Add PEP 621 metadata, runtime deps, and a `dev` optional-dependency group. Delete `requirements*.txt`. Add `.python-version`. CI runs `uv sync --frozen --extra dev` then `uv run pytest`. `uv.lock` is generated once and committed.
   - Pros: Locked, reproducible resolution; single source of truth; `uv add` / `uv run` workflow; one place for tool config (ruff/mypy/pytest) later; matches industry direction.
   - Cons: Largest diff (`uv.lock` is hundreds of lines even though generated); requires a small spec amendment to `readme/spec.md`; one-time risk of a missing transitive or an extras-squash bug at the boundary; depends on `pyproject.toml` being correct on the first cut.
   - Effort: **Medium** (≈120–200 hand-written lines + a generated lockfile).

3. **Staged migration with temporary compatibility** — Same end state as (2), but the PR is split into chained sub-PRs so each step is independently green and reversible:
   - **PR-1 (add uv, keep pip):** add `pyproject.toml` (PEP 621) and `.python-version`, run `uv lock` to generate `uv.lock`; CI gains a new `uv` job **alongside** the existing pip job; both must pass. `requirements*.txt` stay as the legacy source for the pip job. README gains a "uv (recommended)" path while keeping the pip path documented.
   - **PR-2 (switch CI to uv):** remove the pip job; CI uses `uv sync --frozen --extra dev` + `uv run pytest` only. `requirements*.txt` still tracked for the README / external consumers.
   - **PR-3 (drop pip, polish docs):** delete `requirements*.txt`, finalize README in both languages, update `readme/spec.md` to allow uv, re-anchor the PRD `T-007` reference to `pyproject.toml`.
   - Pros: Each step is ≤ ~150 changed lines; the legacy pip path is the rollback plan until PR-3; CI is green at every commit; reviewers see one decision per PR.
   - Cons: Three PRs instead of one; temporary duplication of dependency declarations (mitigated because `pyproject.toml` is canonical and `requirements*.txt` are flagged as legacy in PR-1); needs clear commit/PR hygiene.
   - Effort: **Medium** (sum of slices, each individually Low).

### Recommendation

**Approach 3 — staged migration to `pyproject.toml` + `uv.lock`.**

This is the least-risky path that still delivers the full project-mode outcome:

- The end state is the same as Approach 2: `pyproject.toml` is the source of truth, `uv.lock` is committed, CI is uv-native, `requirements*.txt` are gone.
- The staged shape keeps the working `pip` install as a working fallback until uv is proven in CI, which is exactly what the user asked for ("a strategic plan that does not break the project").
- It also respects the **400-line review budget**: each chained slice is well under 400 changed lines, and `uv.lock` is auto-generated and not hand-reviewed line-by-line.

Concrete shape for PR-1 (the only slice this exploration asks the proposal to commit to first):

1. Add `pyproject.toml` (PEP 621) with `[project]`, `requires-python = ">=3.12"`, runtime dependencies, and an optional `dev` group. Use the exact pins from `requirements*.txt` so resolution is identical.
2. Add `.python-version` with `3.12`.
3. Run `uv lock` once; commit `uv.lock`.
4. Update `.github/workflows/ci.yml` to add a `uv` job (keep the existing pip job for this PR).
5. Update both README files with a "uv (recommended)" section above the existing pip section. Keep the pip section verbatim.
6. Do **not** delete `requirements*.txt`; mark them as legacy in a header comment.

PR-2 and PR-3 land in follow-up changes only after PR-1 is green.

### Risks

- **Extras-squash risk:** the current `requirements.txt` uses extras like `uvicorn[standard]`, `redis[hiredis]`, `celery[redis]`, `python-jose[cryptography]`, `passlib[bcrypt]`, `sqlalchemy[asyncio]`. A naive `dependencies = [...]` rewrite in `pyproject.toml` can drop those extras. Mitigation: declare each extras-bearing package with its extras in the PEP 621 list, and add a smoke step in PR-1 that imports the relevant modules (`asyncpg`, `cryptography`, `bcrypt`, `hiredis`, `uvicorn[standard]`-style entrypoints) under `uv run`.
- **Duplicate deps in `requirements-dev.txt`:** `httpx`, `pytest`, `pytest-asyncio` are listed twice. Resolved automatically by `uv`, but a hand-rolled `pyproject.toml` that copies the file verbatim would inherit the duplication. Mitigation: write the `dev` group by hand, not by transliterating the file.
- **`pyproject.toml` is currently assumed absent by every developer.** The first cut must keep the legacy pip workflow so no one is blocked. Mitigation: PR-1 keeps the pip job green and the pip README path intact.
- **`uv.lock` size and diff noise:** the first commit will add a large auto-generated file. Reviewers should not read it line-by-line. Mitigation: PR-1 description calls this out explicitly; the file is treated as generated.
- **`readme/spec.md` wording:** the current spec requires `venv → dependencies` in the documented order. uv keeps the order but changes the step name. Mitigation: amend the spec in PR-3, not PR-1, so the spec change is reviewable on its own.
- **Alembic `prepend_sys_path`:** `alembic.ini` uses `prepend_sys_path = .`, which works under `uv run alembic` because the project root is on `sys.path`. No code change needed, but the first migration run under uv must be smoke-tested.
- **CI runner vs local Python:** `actions/setup-python` already pins `3.12`; `uv` will pick that up from `.python-version`. Risk: a maintainer on a non-3.12 host gets a clear "Python 3.12 required" error. Mitigation: keep `requires-python = ">=3.12"` in `pyproject.toml` to surface the same constraint locally.

### Ready for Proposal

**Yes.** Next phase is `sdd-propose`, scoped specifically to **PR-1 of the staged migration**:

- Add `pyproject.toml` (PEP 621), `.python-version`, and a generated `uv.lock`.
- Add a parallel `uv` CI job next to the existing pip job.
- Add a "uv (recommended)" section to both READMEs without removing the pip section.
- Do **not** delete `requirements*.txt`; do **not** modify `readme/spec.md`; do **not** modify the PRD `T-007` wording.

PR-2 and PR-3 are recorded here as follow-up slices and will each get their own SDD change after PR-1 merges and CI is green on `main`.
