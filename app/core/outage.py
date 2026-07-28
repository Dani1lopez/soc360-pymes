"""Typed outage foundation — 25-FlowId catalog, policy, retry classification.

PR2 #260: pure primitives with no Redis import, no I/O, and no router coupling.
All identifiers match spec rev 9 and design rev 9 exactly.
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Awaitable, Protocol, TypeVar

from redis.exceptions import ResponseError as RedisResponseErrorLib

from app.core.exceptions import (
    RedisOutageError,
    RedisResponseError,
    RedisTimeoutError,
    RedisUnreachableError,
)

T = TypeVar("T")


# ─────────────────────────────────────────────────────────────────────────────
# AsyncWaiter — injectable deadline seam (spec rev 9 §Async Wait/Timeout)
# ─────────────────────────────────────────────────────────────────────────────

class AsyncWaiter(Protocol):
    """Injectable async deadline seam.

    Production binds ``asyncio.wait_for``; tests inject deterministic
    completion or timeout without sleeping.  MUST propagate
    ``asyncio.CancelledError`` unchanged.
    """

    async def wait(self, awaitable: Awaitable[T], *, timeout: float) -> T: ...


# ─────────────────────────────────────────────────────────────────────────────
# 25-FlowId catalog (exact set — spec rev 9 §25-FlowId)
# ─────────────────────────────────────────────────────────────────────────────

_FLOW_ID_AUTH_LOGIN_RATE_PRECHECK = "auth_login_rate_precheck"
_FLOW_ID_AUTH_REFRESH_RATE_PRECHECK = "auth_refresh_rate_precheck"
_FLOW_ID_AUTH_LOGOUT_RATE_PRECHECK = "auth_logout_rate_precheck"
_FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_PRECHECK = "auth_change_password_rate_precheck"

_FLOW_ID_AUTH_LOGIN_RATE_RECORD = "auth_login_rate_record"
_FLOW_ID_AUTH_REFRESH_RATE_RECORD = "auth_refresh_rate_record"
_FLOW_ID_AUTH_LOGOUT_RATE_RECORD = "auth_logout_rate_record"
_FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_RECORD = "auth_change_password_rate_record"

_FLOW_ID_AUTH_LOGIN_SERVICE = "auth_login_service"
_FLOW_ID_AUTH_REFRESH_SERVICE = "auth_refresh_service"
_FLOW_ID_AUTH_LOGOUT_SERVICE = "auth_logout_service"
_FLOW_ID_AUTH_CHANGE_PASSWORD_SERVICE = "auth_change_password_service"

_FLOW_ID_AUTH_CURRENT_USER_DEP = "auth_current_user_dep"
_FLOW_ID_AUTH_ACCOUNT_LOCKOUT_CHECK = "auth_account_lockout_check"
_FLOW_ID_AUTH_FAILED_ATTEMPT_RECORD = "auth_failed_attempt_record"
_FLOW_ID_AUTH_LOGIN_ATTEMPTS_CLEAR = "auth_login_attempts_clear"
_FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH = "auth_login_event_publish"
_FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE = "auth_change_password_revoke"

_FLOW_ID_USERS_UPDATE_USER_REVOKE = "users_update_user_revoke"
_FLOW_ID_USERS_DEACTIVATE_USER_REVOKE = "users_deactivate_user_revoke"

_FLOW_ID_TENANTS_UPDATE_TENANT_REVOKE = "tenants_update_tenant_revoke"
_FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE = "tenants_deactivate_tenant_revoke"

_FLOW_ID_AUTH_POST_CREDENTIAL_SESSION_LOCK = "auth_post_credential_session_lock"
_FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK = "auth_post_credential_user_deactivate_lock"
_FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK = "auth_tenant_deactivate_lock"

ALL_FLOW_IDS: list[str] = sorted(
    [
        _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK,
        _FLOW_ID_AUTH_REFRESH_RATE_PRECHECK,
        _FLOW_ID_AUTH_LOGOUT_RATE_PRECHECK,
        _FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_PRECHECK,
        _FLOW_ID_AUTH_LOGIN_RATE_RECORD,
        _FLOW_ID_AUTH_REFRESH_RATE_RECORD,
        _FLOW_ID_AUTH_LOGOUT_RATE_RECORD,
        _FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_RECORD,
        _FLOW_ID_AUTH_LOGIN_SERVICE,
        _FLOW_ID_AUTH_REFRESH_SERVICE,
        _FLOW_ID_AUTH_LOGOUT_SERVICE,
        _FLOW_ID_AUTH_CHANGE_PASSWORD_SERVICE,
        _FLOW_ID_AUTH_CURRENT_USER_DEP,
        _FLOW_ID_AUTH_ACCOUNT_LOCKOUT_CHECK,
        _FLOW_ID_AUTH_FAILED_ATTEMPT_RECORD,
        _FLOW_ID_AUTH_LOGIN_ATTEMPTS_CLEAR,
        _FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH,
        _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE,
        _FLOW_ID_USERS_UPDATE_USER_REVOKE,
        _FLOW_ID_USERS_DEACTIVATE_USER_REVOKE,
        _FLOW_ID_TENANTS_UPDATE_TENANT_REVOKE,
        _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE,
        _FLOW_ID_AUTH_POST_CREDENTIAL_SESSION_LOCK,
        _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK,
        _FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK,
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# FlowPolicy — per-FlowId behaviour map (design rev 9)
# ─────────────────────────────────────────────────────────────────────────────

FlowPolicy: dict[str, str] = {
    # ── rate prechecks ──
    _FLOW_ID_AUTH_LOGIN_RATE_PRECHECK: "masked",
    _FLOW_ID_AUTH_REFRESH_RATE_PRECHECK: "masked",
    _FLOW_ID_AUTH_LOGOUT_RATE_PRECHECK: "masked",
    _FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_PRECHECK: "masked",
    # ── rate records ──
    _FLOW_ID_AUTH_LOGIN_RATE_RECORD: "fail_closed",
    _FLOW_ID_AUTH_REFRESH_RATE_RECORD: "fail_closed",
    _FLOW_ID_AUTH_LOGOUT_RATE_RECORD: "fail_closed",
    _FLOW_ID_AUTH_CHANGE_PASSWORD_RATE_RECORD: "fail_closed",
    # ── auth services ──
    _FLOW_ID_AUTH_LOGIN_SERVICE: "fail_closed",
    _FLOW_ID_AUTH_REFRESH_SERVICE: "fail_closed",
    _FLOW_ID_AUTH_LOGOUT_SERVICE: "best_effort",
    _FLOW_ID_AUTH_CHANGE_PASSWORD_SERVICE: "fail_closed",
    # ── dependencies ──
    _FLOW_ID_AUTH_CURRENT_USER_DEP: "fail_closed",
    _FLOW_ID_AUTH_ACCOUNT_LOCKOUT_CHECK: "fail_open",
    _FLOW_ID_AUTH_FAILED_ATTEMPT_RECORD: "best_effort",
    _FLOW_ID_AUTH_LOGIN_ATTEMPTS_CLEAR: "best_effort",
    _FLOW_ID_AUTH_LOGIN_EVENT_PUBLISH: "best_effort",
    # ── revocation ──
    _FLOW_ID_AUTH_CHANGE_PASSWORD_REVOKE: "fail_closed",
    _FLOW_ID_USERS_UPDATE_USER_REVOKE: "fail_closed",
    _FLOW_ID_USERS_DEACTIVATE_USER_REVOKE: "fail_closed",
    _FLOW_ID_TENANTS_UPDATE_TENANT_REVOKE: "fail_closed",
    _FLOW_ID_TENANTS_DEACTIVATE_TENANT_REVOKE: "fail_closed",
    # ── locks ──
    _FLOW_ID_AUTH_POST_CREDENTIAL_SESSION_LOCK: "fail_closed",
    _FLOW_ID_AUTH_POST_CREDENTIAL_USER_DEACTIVATE_LOCK: "fail_closed",
    _FLOW_ID_AUTH_TENANT_DEACTIVATE_LOCK: "fail_closed",
}


# ─────────────────────────────────────────────────────────────────────────────
# RetryableOp — idempotent operations safe to retry (design rev 9)
# ─────────────────────────────────────────────────────────────────────────────

class RetryableOp(str, Enum):
    """Operations proven safe to retry — exactly six members.

    Non-members (INCR, XADD, pipeline, loop) are NEVER retried.
    """

    PING = "PING"
    IS_TOKEN_REVOKED = "IS_TOKEN_REVOKED"
    GET_ACTIVE_JTIS = "GET_ACTIVE_JTIS"
    REVOKE_ACCESS_TOKEN = "REVOKE_ACCESS_TOKEN"
    TRACK_JTI = "TRACK_JTI"
    UNTRACK_JTI = "UNTRACK_JTI"


# ─────────────────────────────────────────────────────────────────────────────
# classify_redis_error — pure transport exception classifier
# ─────────────────────────────────────────────────────────────────────────────

def classify_redis_error(exc: BaseException) -> RedisOutageError:
    """Map a transport exception to a typed RedisOutageError subclass.

    This is a **pure function** — no I/O, no module state, no side effects.
    The returned exception chains ``exc`` as ``__cause__`` so reviewers can
    see the root transport failure alongside the typed outcome.

    Mapping (design rev 9):

    * ``ConnectionError`` / ``ConnectionRefusedError`` → ``RedisUnreachableError``
    * ``asyncio.TimeoutError``                     → ``RedisTimeoutError``
    * ``redis.exceptions.ResponseError``           → ``RedisResponseError``
    * anything else                                → ``RedisUnreachableError`` (safe default)
    """
    if isinstance(exc, asyncio.TimeoutError):
        result: RedisOutageError = RedisTimeoutError(str(exc))
    elif isinstance(exc, RedisResponseErrorLib):
        result = RedisResponseError(str(exc))
    elif isinstance(exc, ConnectionError):
        result = RedisUnreachableError(str(exc))
    else:
        result = RedisUnreachableError(str(exc))

    result.__cause__ = exc
    return result
