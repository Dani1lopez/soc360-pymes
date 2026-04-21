# Tasks: Refresh Token Replay Race Condition Fix (#16)

**Issue**: #16 — HIGH severity security fix for refresh token replay attack  
**Branch**: fix/f1-refresh-token-race  
**Mode**: Strict TDD (RED → GREEN → REFACTOR)

---

## Phase 1: Tests — RED (Write Failing Tests)

All tests written before implementation. Each must fail initially.

### 1.1 Unit Tests — Test Utilities & Fixtures
- [ ] **1.1.1** Create `tests/modules/auth/conftest.py` with async DB session fixture for isolated tests
- [ ] **1.1.2** Add `create_refresh_token()` factory helper for test data setup
- [ ] **1.1.3** Add `mock_redis()` fixture for side-effect isolation

### 1.2 Unit Tests — Happy Path Scenario
- [ ] **1.2.1** Write `test_refresh_token_happy_path()` — valid token returns new tokens
- [ ] **1.2.2** Assert: old token revoked, new tokens issued, Redis notified
- [ ] **1.2.3** Verify: test FAILS (no implementation yet)

### 1.3 Unit Tests — Concurrent Race Scenario
- [ ] **1.3.1** Write `test_refresh_token_concurrent_race()` — two concurrent requests with same token
- [ ] **1.3.2** Assert: first request succeeds, second returns 401 (lock unavailable)
- [ ] **1.3.3** Verify: test FAILS (no locking yet)

### 1.4 Unit Tests — Already-Revoked Scenario
- [ ] **1.4.1** Write `test_refresh_token_already_revoked()` — request with revoked token
- [ ] **1.4.2** Assert: returns 401, no new tokens issued
- [ ] **1.4.3** Verify: test FAILS (no revocation check yet)

### 1.5 Unit Tests — Expired Token Scenario
- [ ] **1.5.1** Write `test_refresh_token_expired()` — request with expired token
- [ ] **1.5.2** Assert: returns 401, no new tokens issued
- [ ] **1.5.3** Verify: test FAILS (no expiry check yet)

### 1.6 Integration Tests
- [ ] **1.6.1** Write `test_refresh_token_race_integration()` using `asyncio.gather()` for true concurrency
- [ ] **1.6.2** Assert: only one request succeeds, DB state consistent
- [ ] **1.6.3** Verify: test FAILS (no transaction wrapping yet)

---

## Phase 2: Core Implementation — GREEN (Make Tests Pass)

### 2.1 Database Layer — Locking Query
- [ ] **2.1.1** Modify `app/modules/auth/service.py`: add `SELECT FOR UPDATE SKIP LOCKED` query
- [ ] **2.1.2** Use `with_for_update(skip_locked=True)` in SQLAlchemy async query
- [ ] **2.1.3** Verify: unit test 1.3.1 now PASSES (lock acquisition works)

### 2.2 Service Layer — Transaction Wrapping
- [ ] **2.2.1** Wrap entire `refresh_tokens()` function in single DB transaction (`async with db.begin()`)
- [ ] **2.2.2** Move token lookup + lock into transaction block
- [ ] **2.2.3** Verify: integration test 1.6.1 now PASSES (atomicity works)

### 2.3 Security Checks — Double Validation
- [ ] **2.3.1** After acquiring lock, double-check `revoked_at IS NULL`
- [ ] **2.3.2** After acquiring lock, double-check `expires_at > now()`
- [ ] **2.3.3** If checks fail, raise 401 Unauthorized (not 409)
- [ ] **2.3.4** Verify: tests 1.4.1 and 1.5.1 now PASS (security checks work)

### 2.4 Token Rotation Logic — Happy Path
- [ ] **2.4.1** Implement: revoke old token (set `revoked_at = now()`)
- [ ] **2.4.2** Implement: generate new access + refresh tokens
- [ ] **2.4.3** Implement: persist new tokens in same transaction
- [ ] **2.4.4** Verify: test 1.2.1 now PASSES (happy path works)

### 2.5 Redis Side Effects — Best-Effort
- [ ] **2.5.1** Move Redis `delete()` and `setex()` calls OUTSIDE DB transaction
- [ ] **2.5.2** Wrap Redis ops in try/except (best-effort, don't fail on Redis error)
- [ ] **2.5.3** Verify: test 1.2.1 still PASSES (Redis integration works)

---

## Phase 3: Refactor — Clean Implementation

### 3.1 Code Quality
- [ ] **3.1.1** Extract token validation logic into `_validate_token_for_rotation()` helper
- [ ] **3.1.2** Extract token generation into `_generate_token_pair()` helper
- [ ] **3.1.3** Add type hints to all modified functions
- [ ] **3.1.4** Add docstrings explaining race condition protection

### 3.2 Error Handling
- [ ] **3.2.1** Ensure all 401 responses have consistent error message format
- [ ] **3.2.2** Add logging for race condition detection (security audit trail)
- [ ] **3.2.3** Verify: all tests still PASS after refactor

### 3.3 Performance
- [ ] **3.3.1** Verify `SKIP LOCKED` doesn't hold transaction longer than necessary
- [ ] **3.3.2** Check query execution plan for token lookup (should use index)
- [ ] **3.3.3** Verify: integration test 1.6.1 still PASSES under load

---

## Phase 4: Verification & Completion

### 4.1 Test Coverage
- [ ] **4.1.1** Run full test suite: `pytest tests/modules/auth/ -v`
- [ ] **4.1.2** Verify coverage ≥ 90% for `app/modules/auth/service.py`
- [ ] **4.1.3** Run concurrency stress test: 100 parallel requests, only 1 succeeds

### 4.2 Regression Testing
- [ ] **4.2.1** Run existing auth tests to ensure no breakage
- [ ] **4.2.2** Verify login flow still works (unaffected by changes)
- [ ] **4.2.3** Verify logout flow still works (unaffected by changes)

### 4.3 Security Audit
- [ ] **4.3.1** Confirm: no token can be refreshed twice (replay impossible)
- [ ] **4.3.2** Confirm: 401 returned on lock failure (no concurrency info leaked)
- [ ] **4.3.3** Confirm: Redis failures don't compromise DB consistency

### 4.4 Documentation
- [ ] **4.4.1** Update function docstrings with race condition explanation
- [ ] **4.4.2** Add CHANGELOG entry for security fix
- [ ] **4.4.3** Link PR to issue #16 with `Fixes #16`

---

## Task Summary

| Phase | Tasks | Focus |
|-------|-------|-------|
| Phase 1 | 13 | RED — Write all failing tests first (TDD) |
| Phase 2 | 12 | GREEN — Implement to make tests pass |
| Phase 3 | 8  | REFACTOR — Clean, type-safe, documented |
| Phase 4 | 9  | VERIFY — Coverage, regression, security audit |
| **Total** | **42** | |

### Implementation Order

Strict TDD sequence:
1. **Phase 1 (RED)**: Write ALL tests first — they must fail
2. **Phase 2 (GREEN)**: Implement minimal code to pass each test
3. **Phase 3 (REFACTOR)**: Clean up without changing behavior
4. **Phase 4 (VERIFY)**: Full test suite + security audit

### Expected Artifacts

- Modified: `app/modules/auth/service.py`
- Created: `tests/modules/auth/test_refresh_token_race.py`
- Created: `tests/modules/auth/conftest.py` (race condition fixtures)
- Updated: `CHANGELOG.md` (security fix entry)

### Next Step

Start Phase 1.1 — create test fixtures, then write failing tests for all 4 spec scenarios.
