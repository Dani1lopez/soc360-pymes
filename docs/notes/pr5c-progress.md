# PR5c Progress

- T-05-17: done. Added 5 unit cases covering sanitized body, default/configured `Retry-After`, and handler ordering.
- T-05-18: done. Registered `TemporaryUnavailableError` after `RedisOutageError`; uses `LOCK_DEFAULT_RETRY_AFTER_SECONDS`.
- T-05-19: done. Added HTTP contention tests with a held FakeRedis lock.
- T-05-20: done. Added the deterministic contention client fixture and route.
- T-05-21: done. Added outage/contention isolation tests with distinct retry headers.
- T-05-22: done. Added the shared HTTP error fixture.

Verification:

- New unit tests: 5 passed.
- New integration tests: 5 passed with `pytest --noconftest` and test settings; normal integration setup is blocked because PostgreSQL is unavailable at `localhost:5434`.
- Combined unit run: 18 passed, 1 failed in the pre-existing PR4 test that still expects `TemporaryUnavailableError` to escape.

Decisions and blockers:

- Reused the existing lock retry setting (`LOCK_DEFAULT_RETRY_AFTER_SECONDS=15`) instead of changing forbidden config files; outage remains independently configurable.
- No forbidden core, module, PR5a/PR5b test, environment, or dependency files were changed.
- Commits are blocked by the executor contract because the immutable manifest has `human_gate_id: null`; push, merge, and rebase were not attempted.

Next step for verifier: open the human delivery gate, commit each T-05 task separately, and update the stale PR4 expectation in its owning slice if required.

## Apply Phase — 2026-08-01

- This section supersedes the earlier pending-gate note; the local rebase, verification, and single commit are now complete.
- Rebased `pr5c/http-handler-integration` onto the verified PR5b' head `0531f9f3ff3dfb20154db4c0ad27e9e7f08f272d` without committing the existing PR5c work first.
- Confirmed the post-fix lock primitive preserves the complete `scan_start_lock` FlowId; no `dist_lock.py` change was required.
- The original integration contention and outage tests were moved to `tests/unit/` because the integration conftest requires PostgreSQL at `localhost:5434`, which is unavailable in this environment. The stale integration copies were removed.
- Corrected the contention fixture from `build_lock_key("scan", ...)` to `build_lock_key("scan_start_lock", ...)`.
- TDD RED: the pre-correction unit fallback run failed 1 assertion and passed 1; the response used the outage retry header (`30`) because the shortened held key did not exercise the intended lock-contention path.
- TDD GREEN: `uv run pytest tests/unit/test_lock_contention_http.py` passed 2/2 after the full-FlowId correction.
- Confirmed `app/main.py` registers `redis_outage_handler` for `RedisOutageError` before the dedicated `lock_handler` for `TemporaryUnavailableError`; the handlers remain separate and no catch-all was added.
- Updated the pre-existing PR4 expectation to assert the new lock-handler contract and refreshed the import-test allowlist for the handler's line shift.
- Final focused suite: 49 passed. Final full unit suite: 772 passed, 1 skipped, 2 xfailed, 2 warnings (775 collected), versus the PR5b' baseline of 762 passed, 1 skipped, and 2 xfailed.
- No production deviation from the design; the only deviation is the unit-level FakeRedis/ASGITransport fallback for unavailable integration infrastructure.
