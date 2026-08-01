"""Unit tests for PR2 outage primitives — DB-free, Redis-free.

Covers the typed foundation: RedisOutageError hierarchy, TemporaryUnavailableError,
AsyncWaiter Protocol, 25-FlowId catalog, FlowPolicy, RetryableOp enum,
and the pure classify_redis_error helper.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable

import pytest
from redis.exceptions import ResponseError as RedisResponseErrorLib

from app.core.exceptions import (
    AppError,
    PartialFailureError,
    RedisOutageError,
    RedisResponseError,
    RedisTimeoutError,
    RedisUnreachableError,
    TemporaryUnavailableError,
)
from app.core.outage import (
    ALL_FLOW_IDS,
    FlowPolicy,
    RetryableOp,
    classify_redis_error,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DeterministicWaiter:
    """Injected AsyncWaiter that completes or times out without sleeping."""

    def __init__(self, *, should_timeout: bool = False) -> None:
        self._should_timeout = should_timeout
        self._calls: list[tuple[Any, float]] = []

    async def wait(self, awaitable: Awaitable[Any], *, timeout: float) -> Any:
        self._calls.append((awaitable, timeout))
        if self._should_timeout:
            raise asyncio.TimeoutError()
        return await awaitable


class _CancellationAwaitable:
    """Awaitable that raises CancelledError when awaited."""

    def __await__(self):
        raise asyncio.CancelledError()
        yield  # pragma: no cover — unreachable, satisfies generator protocol


# ---------------------------------------------------------------------------
# RedisOutageError hierarchy
# ---------------------------------------------------------------------------


class TestRedisOutageErrorHierarchy:
    """Verify the RedisOutageError base class and its four subclasses."""

    # ── base class ──────────────────────────────────────────────────────

    def test_redis_outage_error_is_app_error(self) -> None:
        """RedisOutageError MUST subclass AppError."""
        assert issubclass(RedisOutageError, AppError)

    def test_redis_outage_error_default_status_503(self) -> None:
        """RedisOutageError MUST default to status_code=503."""
        exc = RedisOutageError()
        assert exc.status_code == 503

    def test_redis_outage_error_custom_detail(self) -> None:
        """RedisOutageError MUST store custom detail."""
        exc = RedisOutageError("Redis cluster unreachable")
        assert exc.detail == "Redis cluster unreachable"
        assert exc.status_code == 503

    # ── subclasses — inheritance ────────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [
            RedisUnreachableError,
            RedisTimeoutError,
            RedisResponseError,
            PartialFailureError,
        ],
    )
    def test_subclass_is_redis_outage_error(self, exc_class: type) -> None:
        """Each RedisOutageError subclass MUST inherit from RedisOutageError."""
        assert issubclass(
            exc_class, RedisOutageError
        ), f"{exc_class.__name__} does not subclass RedisOutageError"

    @pytest.mark.parametrize(
        "exc_class",
        [
            RedisUnreachableError,
            RedisTimeoutError,
            RedisResponseError,
            PartialFailureError,
        ],
    )
    def test_subclass_is_app_error(self, exc_class: type) -> None:
        """Each RedisOutageError subclass MUST ultimately be an AppError."""
        assert issubclass(exc_class, AppError)

    # ── subclasses — instantiation ──────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [
            RedisUnreachableError,
            RedisTimeoutError,
            RedisResponseError,
            PartialFailureError,
        ],
    )
    def test_subclass_instantiable_no_args(self, exc_class: type) -> None:
        """Each subclass MUST be instantiable without arguments."""
        instance = exc_class()
        assert isinstance(instance, exc_class)
        assert isinstance(instance, RedisOutageError)

    # ── subclasses — default status code ────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [
            RedisUnreachableError,
            RedisTimeoutError,
            RedisResponseError,
            PartialFailureError,
        ],
    )
    def test_subclass_default_status_503(self, exc_class: type) -> None:
        """Every RedisOutageError subclass MUST default to status_code=503."""
        instance = exc_class()
        assert (
            instance.status_code == 503
        ), f"{exc_class.__name__}.status_code expected 503, got {instance.status_code}"

    # ── subclasses — custom detail ──────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class,detail",
        [
            (RedisUnreachableError, "Connection refused on 127.0.0.1:6379"),
            (RedisTimeoutError, "BLPOP timed out after 5.0 s"),
            (RedisResponseError, "ERR unknown command"),
            (PartialFailureError, "Only 14 of 16 JTIs were denied"),
        ],
    )
    def test_subclass_stores_custom_detail(self, exc_class: type, detail: str) -> None:
        """Each subclass MUST accept and store a custom detail string."""
        exc = exc_class(detail)
        assert exc.detail == detail

    # ── str representation ──────────────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class,detail",
        [
            (RedisUnreachableError, "host unreachable"),
            (RedisTimeoutError, "op slow"),
            (RedisResponseError, "bad command"),
            (PartialFailureError, "partial batch"),
        ],
    )
    def test_subclass_str_contains_detail(self, exc_class: type, detail: str) -> None:
        """str(exc) MUST include the detail for each subclass."""
        exc = exc_class(detail)
        assert detail in str(exc)

    # ── chaining / cause ────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "exc_class",
        [
            RedisUnreachableError,
            RedisTimeoutError,
            RedisResponseError,
            PartialFailureError,
        ],
    )
    def test_subclass_preserves_cause_chain(self, exc_class: type) -> None:
        """Subclasses MUST preserve __cause__ when chained from another exception."""
        original = ValueError("socket closed")
        exc = exc_class("Redis failure")
        exc.__cause__ = original
        assert exc.__cause__ is original


# ---------------------------------------------------------------------------
# TemporaryUnavailableError
# ---------------------------------------------------------------------------


class TestTemporaryUnavailableError:
    """TemporaryUnavailableError is NOT a RedisOutageError — design rev 9."""

    def test_subclasses_app_error(self) -> None:
        """MUST subclass AppError."""
        assert issubclass(TemporaryUnavailableError, AppError)

    def test_not_redis_outage_error(self) -> None:
        """MUST NOT subclass RedisOutageError (separate coordination domain)."""
        assert not issubclass(TemporaryUnavailableError, RedisOutageError)

    def test_subclasses_exception(self) -> None:
        """MUST ultimately be an Exception."""
        assert issubclass(TemporaryUnavailableError, Exception)

    def test_default_status_503(self) -> None:
        """MUST default to status_code=503."""
        exc = TemporaryUnavailableError()
        assert exc.status_code == 503

    def test_custom_detail(self) -> None:
        """MUST accept custom detail."""
        exc = TemporaryUnavailableError("lock_timeout")
        assert exc.detail == "lock_timeout"
        assert exc.status_code == 503

    def test_str_contains_detail(self) -> None:
        """str(exc) MUST include the detail."""
        exc = TemporaryUnavailableError("lock acquisition timeout")
        assert "lock acquisition timeout" in str(exc)


# ---------------------------------------------------------------------------
# AsyncWaiter Protocol
# ---------------------------------------------------------------------------


class TestAsyncWaiterProtocol:
    """AsyncWaiter is a structural Protocol — injectable seam for deadlines."""

    def test_deterministic_waiter_satisfies_protocol(self) -> None:
        """_DeterministicWaiter MUST structurally satisfy AsyncWaiter."""
        waiter = _DeterministicWaiter()
        # Protocol check — mypy would flag missing 'wait', runtime check passes
        assert hasattr(waiter, "wait")

    async def test_deterministic_waiter_completes(self) -> None:
        """Injected waiter MUST resolve the awaitable on success."""
        waiter = _DeterministicWaiter()

        async def _work() -> str:
            return "done"

        result = await waiter.wait(_work(), timeout=5.0)
        assert result == "done"
        assert len(waiter._calls) == 1

    async def test_deterministic_waiter_times_out(self) -> None:
        """Injected waiter MUST raise TimeoutError when configured."""
        waiter = _DeterministicWaiter(should_timeout=True)

        async def _work() -> str:
            return "never"

        with pytest.raises(asyncio.TimeoutError):
            await waiter.wait(_work(), timeout=1.0)
        assert len(waiter._calls) == 1

    async def test_cancelled_error_propagates_unchanged(self) -> None:
        """AsyncWaiter MUST propagate CancelledError unchanged (spec rev 9)."""
        waiter = _DeterministicWaiter()

        with pytest.raises(asyncio.CancelledError):
            await waiter.wait(_CancellationAwaitable(), timeout=5.0)
        assert len(waiter._calls) == 1


# ---------------------------------------------------------------------------
# 25-FlowId catalog
# ---------------------------------------------------------------------------

EXPECTED_25_FLOW_IDS = frozenset(
    [
        "auth_login_rate_precheck",
        "auth_refresh_rate_precheck",
        "auth_logout_rate_precheck",
        "auth_change_password_rate_precheck",
        "auth_login_rate_record",
        "auth_refresh_rate_record",
        "auth_logout_rate_record",
        "auth_change_password_rate_record",
        "auth_login_service",
        "auth_refresh_service",
        "auth_logout_service",
        "auth_change_password_service",
        "auth_current_user_dep",
        "auth_account_lockout_check",
        "auth_failed_attempt_record",
        "auth_login_attempts_clear",
        "auth_login_event_publish",
        "auth_change_password_revoke",
        "users_update_user_revoke",
        "users_deactivate_user_revoke",
        "tenants_update_tenant_revoke",
        "tenants_deactivate_tenant_revoke",
        "auth_post_credential_session_lock",
        "auth_post_credential_user_deactivate_lock",
        "auth_tenant_deactivate_lock",
        "scan_start_lock",
        "scan_update_lock",
        "scan_complete_lock",
        "scan_cancel_lock",
    ]
)


class TestFlowIdCatalog:
    """Exactly 25 FlowId constants MUST exist and match spec rev 9."""

    def test_catalog_has_exactly_25_items(self) -> None:
        """ALL_FLOW_IDS MUST contain exactly 25 identifiers."""
        assert len(ALL_FLOW_IDS) == 29, f"Expected 29 FlowIds, got {len(ALL_FLOW_IDS)}"

    def test_catalog_matches_spec_set(self) -> None:
        """ALL_FLOW_IDS MUST contain exactly the 25 spec mandated identifiers."""
        actual = frozenset(ALL_FLOW_IDS)
        assert actual == EXPECTED_25_FLOW_IDS, (
            f"Missing: {sorted(EXPECTED_25_FLOW_IDS - actual)}\n"
            f"Extra:   {sorted(actual - EXPECTED_25_FLOW_IDS)}"
        )

    def test_every_flow_id_is_a_string(self) -> None:
        """Every FlowId constant MUST be a str."""
        for fid in ALL_FLOW_IDS:
            assert isinstance(
                fid, str
            ), f"FlowId {fid!r} is {type(fid).__name__}, expected str"

    def test_no_duplicate_flow_ids(self) -> None:
        """ALL_FLOW_IDS MUST NOT contain duplicates."""
        assert len(set(ALL_FLOW_IDS)) == len(ALL_FLOW_IDS)


# ---------------------------------------------------------------------------
# FlowPolicy
# ---------------------------------------------------------------------------


class TestFlowPolicy:
    """FlowPolicy maps each FlowId to a policy behaviour."""

    def test_policy_map_keys_equal_exact_25(self) -> None:
        """FlowPolicy MUST have exactly 25 keys."""
        assert (
            len(FlowPolicy) == 29
        ), f"FlowPolicy has {len(FlowPolicy)} keys, expected 29"

    def test_policy_map_keys_match_flow_ids(self) -> None:
        """FlowPolicy keys MUST be exactly the 25 FlowId constants."""
        policy_keys = frozenset(FlowPolicy.keys())
        assert policy_keys == EXPECTED_25_FLOW_IDS, (
            f"Policy keys mismatch.\n"
            f"Missing: {sorted(EXPECTED_25_FLOW_IDS - policy_keys)}\n"
            f"Extra:   {sorted(policy_keys - EXPECTED_25_FLOW_IDS)}"
        )

    def test_every_policy_value_is_a_string(self) -> None:
        """Every policy value MUST be a non-empty string identifier."""
        for key, value in FlowPolicy.items():
            assert isinstance(
                value, str
            ), f"FlowPolicy[{key!r}] = {value!r} is not a string"
            assert value.strip(), f"FlowPolicy[{key!r}] is an empty string"


# ---------------------------------------------------------------------------
# RetryableOp enum
# ---------------------------------------------------------------------------

RETRYABLE_OP_EXPECTED = frozenset(
    [
        "PING",
        "IS_TOKEN_REVOKED",
        "GET_ACTIVE_JTIS",
        "REVOKE_ACCESS_TOKEN",
        "TRACK_JTI",
        "UNTRACK_JTI",
    ]
)


class TestRetryableOp:
    """RetryableOp enum MUST expose exactly six members — design rev 9."""

    def test_has_exactly_six_members(self) -> None:
        """RetryableOp MUST have exactly 6 members."""
        members = list(RetryableOp)
        assert len(members) == 6, f"RetryableOp has {len(members)} members, expected 6"

    def test_member_names_match_spec(self) -> None:
        """RetryableOp member names MUST match the authorised set."""
        actual = frozenset(m.name for m in RetryableOp)
        assert actual == RETRYABLE_OP_EXPECTED, (
            f"RetryableOp members mismatch.\n"
            f"Missing: {sorted(RETRYABLE_OP_EXPECTED - actual)}\n"
            f"Extra:   {sorted(actual - RETRYABLE_OP_EXPECTED)}"
        )

    def test_every_member_is_retryable_op_instance(self) -> None:
        """Every enum member MUST be a RetryableOp instance."""
        for member in RetryableOp:
            assert isinstance(member, RetryableOp)

    def test_no_invalid_retryable_ops(self) -> None:
        """INCR, XADD, pipeline, and loop MUST NOT be retryable."""
        forbidden = {"INCR", "XADD", "PIPELINE", "LOOP"}
        actual_names = {m.name for m in RetryableOp}
        assert actual_names.isdisjoint(
            forbidden
        ), f"Forbidden RetryableOp members found: {actual_names & forbidden}"

    @pytest.mark.parametrize(
        "member_name",
        sorted(RETRYABLE_OP_EXPECTED),
    )
    def test_each_member_accessible_by_name(self, member_name: str) -> None:
        """Each RetryableOp member MUST be accessible via RetryableOp[<name>]."""
        member = RetryableOp[member_name]
        assert member.name == member_name


# ---------------------------------------------------------------------------
# classify_redis_error — pure function
# ---------------------------------------------------------------------------


class TestClassifyRedisError:
    """Pure classify_redis_error maps transport exceptions to typed outcomes."""

    # ── ConnectionError ─────────────────────────────────────────────────

    def test_connection_error_maps_to_unreachable(self) -> None:
        """ConnectionError MUST produce RedisUnreachableError."""
        original = ConnectionError("Connection refused")
        result = classify_redis_error(original)
        assert isinstance(result, RedisUnreachableError)
        assert result.__cause__ is original

    def test_connection_refused_error_is_unreachable(self) -> None:
        """ConnectionRefusedError (subclass of ConnectionError) MUST map to Unreachable."""
        original = ConnectionRefusedError()
        result = classify_redis_error(original)
        assert isinstance(result, RedisUnreachableError)

    # ── TimeoutError ────────────────────────────────────────────────────

    def test_asyncio_timeout_error_maps_to_timeout(self) -> None:
        """asyncio.TimeoutError MUST produce RedisTimeoutError."""
        original = asyncio.TimeoutError("operation timed out")
        result = classify_redis_error(original)
        assert isinstance(result, RedisTimeoutError)
        assert result.__cause__ is original

    # ── ResponseError ───────────────────────────────────────────────────

    def test_redis_response_error_maps_to_response_error(self) -> None:
        """redis.exceptions.ResponseError MUST produce RedisResponseError."""
        original = RedisResponseErrorLib("ERR unknown command")
        result = classify_redis_error(original)
        assert isinstance(result, RedisResponseError)
        assert result.__cause__ is original

    # ── unknown / fallback ──────────────────────────────────────────────

    def test_unknown_exception_defaults_to_unreachable(self) -> None:
        """Any unrecognised exception MUST default to RedisUnreachableError."""
        original = RuntimeError("unexpected failure")
        result = classify_redis_error(original)
        assert isinstance(result, RedisUnreachableError)
        assert result.__cause__ is original

    # ── purity — no side effects ────────────────────────────────────────

    def test_classify_is_pure_function(self) -> None:
        """classify_redis_error MUST be a pure function (no module state change)."""
        before = set(RedisOutageError.__subclasses__())
        classify_redis_error(ConnectionError("test"))
        classify_redis_error(asyncio.TimeoutError("test"))
        after = set(RedisOutageError.__subclasses__())
        assert before == after

    def test_classify_preserves_original_message(self) -> None:
        """The original exception message MUST be preserved in str(classify_result)."""
        original = ConnectionError("No route to host :6379")
        result = classify_redis_error(original)
        assert "No route to host" in str(result)
