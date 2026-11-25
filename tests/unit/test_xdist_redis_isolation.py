"""xdist Redis isolation (XD-01): worker-specific Redis logical DBs.

Direct tests must not share Redis state across pytest-xdist workers:

- ``os.environ["REDIS_DB"]`` is pinned before ``app.core`` imports, so the
  app settings and their connection pool bind to a worker-specific DB.
- ``tenant_client``'s real Redis client (and its flushdb teardown) uses the
  same worker-specific DB.
- The event-bus E2E tests resolve their Redis URL from ``settings.REDIS_DB``,
  which must equal the worker-specific DB assigned for this worker.

Mapping rules (bounded to Redis's default 16 logical databases):

- Serial (no ``PYTEST_XDIST_WORKER``): db=15 (app/Toxiproxy flush target)
  and db=14 (tenant_client) behave exactly as before this change.
- Toxiproxy fixtures (``toxiproxy_session`` / ``toxiproxy_client``) and
  the shared proxy DB flush are serial-only: the proxy is one global
  endpoint (0.0.0.0:26379) for the whole test run, so under xdist the
  fixtures skip and the flush helper fails closed instead of touching
  worker DBs. Fault-injection tests run in CI's dedicated serial
  Toxiproxy gate.
- Under xdist: app pool gets a worker-unique DB derived from the worker's
  index, shifted by +1 so no worker ever lands on db=0 (reserved for
  ad-hoc dev traffic); tenant_client shares the app pool's DB; db=14 is
  reserved for the serial tenant fixture; db=15 is reserved for serial
  Toxiproxy. Indices that cannot map into 1..13 without colliding with
  those reservations are rejected instead of silently colliding.
"""
from __future__ import annotations

import os
from unittest import mock

import pytest


def _worker_scoped_redis_db(worker_id: str) -> int:
    """Mirror of tests/conftest._worker_scoped_redis_db — import-protected.

    Imported lazily by tests so a collection-time ImportError does not hide
    a missing helper behind machinery noise. This module exercises the
    helper in isolation (unit level) and the fakes at behavior level.
    """
    from tests.conftest import _worker_scoped_redis_db as impl

    return impl(worker_id)


# ---------------------------------------------------------------------------
# Mapping rules (pure function level)
# ---------------------------------------------------------------------------


class TestWorkerScopedRedisDbMapping:
    def test_serial_worker_id_yields_default_db_15(self):
        assert _worker_scoped_redis_db("") == 15

    def test_serial_tenant_client_uses_db_14(self):
        from tests.conftest import _tenant_client_redis_db

        assert _tenant_client_redis_db("") == 14

    def test_gw0_maps_to_first_worker_db(self):
        # Shifted by +1 so gw0 never lands on db=0 (ad-hoc dev traffic).
        assert _worker_scoped_redis_db("gw0") == 1

    def test_gw1_maps_to_second_worker_db(self):
        assert _worker_scoped_redis_db("gw1") == 2

    def test_gw12_is_last_supported_worker_index(self):
        # db indices 14 and 15 are reserved (serial tenant / serial Toxiproxy),
        # and db 0 is avoided, so the last valid worker index is 12 -> db 13.
        assert _worker_scoped_redis_db("gw12") == 13

    def test_gw13_is_rejected_instead_of_colliding(self):
        with pytest.raises(RuntimeError, match="gw13"):
            _worker_scoped_redis_db("gw13")

    def test_gw99_is_rejected_instead_of_colliding(self):
        with pytest.raises(RuntimeError, match="gw99"):
            _worker_scoped_redis_db("gw99")

    def test_malformed_worker_id_is_rejected(self):
        with pytest.raises(RuntimeError, match="gwX"):
            _worker_scoped_redis_db("gwX")

    def test_reservations_are_outside_worker_range(self):
        # db 0 is avoided (ad-hoc dev traffic) and db 14/15 stay exclusive
        # to serial fixtures; no gw index maps to any of those.
        assigned = {_worker_scoped_redis_db(f"gw{i}") for i in range(13)}
        assert assigned == set(range(1, 14))
        assert 0 not in assigned and 14 not in assigned and 15 not in assigned


# ---------------------------------------------------------------------------
# Behavior: actual xdist worker env pinning (runs only under -n >= 2)
# ---------------------------------------------------------------------------


class TestWorkerEnvPinnedInRealWorker:
    def test_pinned_env_and_settings_match_worker_db(self):
        # Proves the actual worker process ended up isolated even when the
        # outer environment exports REDIS_DB=15 (CI parity). Skipped in
        # serial runs; the serial pin contract is covered above.
        worker = os.environ.get("PYTEST_XDIST_WORKER")
        if not worker:
            pytest.skip("requires a real pytest-xdist worker (run with -n >= 2)")
        import tests.conftest as ct

        expected = ct._worker_scoped_redis_db(worker)
        assert os.environ["REDIS_DB"] == str(expected)
        from app.core.config import settings

        assert settings.REDIS_DB == expected


# ---------------------------------------------------------------------------
# Toxiproxy fixtures are serial-only (XD-01 findings: shared proxy/flush)
# ---------------------------------------------------------------------------


class TestToxiproxySerialOnlyGuard:
    """The Toxiproxy proxy is one global endpoint for the whole test run.

    ``toxiproxy_session`` binds a single proxy named ``redis`` listening on
    0.0.0.0:26379, and the fixture's DB flush targets the reserved serial
    db 15. Two xdist workers touching it would race on the same toxic set
    and reset each other's state, so the fixtures must never run under
    xdist: fault-injection tests live in CI's dedicated serial Toxiproxy
    gate and the parallel selection already excludes them.
    """

    def test_guard_allows_serial_runs(self, monkeypatch):
        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        from tests import conftest as ct

        assert ct._assert_serial_toxiproxy() is None

    def test_guard_rejects_xdist_workers(self, monkeypatch):
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
        from tests import conftest as ct

        with pytest.raises(RuntimeError, match="serial"):
            ct._assert_serial_toxiproxy()

    def test_flush_toxiproxy_database_is_serial_only(self, monkeypatch):
        # Defense-in-depth: even if the flush helper is reached under a
        # worker, it must fail closed BEFORE opening any Redis connection
        # instead of flushing an arbitrary worker DB while the proxy is
        # still shared.
        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
        from tests import conftest as ct

        coro = ct._flush_toxiproxy_database()
        try:
            with pytest.raises(RuntimeError, match="serial"):
                # Drives the coroutine until its first await: the
                # serial-only guard raises before any connection opens.
                coro.send(None)
        finally:
            coro.close()

    def test_both_toxiproxy_fixtures_guard_before_proxy_setup(self):
        # Comparing raw-source string offsets (the previous approach) is
        # unsound: ``str.find()`` matches text inside comments and
        # docstrings too, so a marker mentioned in a comment ABOVE the
        # real guard call would satisfy the assertion without the guard
        # actually running first. Parse the fixture's AST instead and
        # compare line numbers of the actual executable Call/Yield nodes
        # — comments and docstring text can never produce those nodes.
        import ast
        import inspect
        import textwrap

        from tests import conftest as ct

        def _qualified_call_name(node: ast.Call) -> str | None:
            func = node.func
            if isinstance(func, ast.Name):
                return func.id
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                return f"{func.value.id}.{func.attr}"
            return None

        def _first_lineno(tree: ast.AST, predicate) -> int | None:
            linenos = [
                node.lineno
                for node in ast.walk(tree)
                if predicate(node)
            ]
            return min(linenos) if linenos else None

        proxy_touch_markers = {
            # toxiproxy_session constructs the controller and calls
            # ensure_proxy immediately after the guard.
            ct.toxiproxy_session.__wrapped__: "ToxiproxyTransportController",
            # toxiproxy_client's reset_state() touches the shared proxy via
            # reset_toxics()/asyncio.gather(), scheduled with asyncio.wait_for.
            ct.toxiproxy_client.__wrapped__: "asyncio.wait_for",
        }

        for fixture, proxy_marker in proxy_touch_markers.items():
            source = textwrap.dedent(inspect.getsource(fixture))
            tree = ast.parse(source)

            guard_lineno = _first_lineno(
                tree,
                lambda n: isinstance(n, ast.Call)
                and _qualified_call_name(n) == "_skip_toxiproxy_under_xdist",
            )
            yield_lineno = _first_lineno(
                tree, lambda n: isinstance(n, (ast.Yield, ast.YieldFrom))
            )
            proxy_lineno = _first_lineno(
                tree,
                lambda n: isinstance(n, ast.Call)
                and _qualified_call_name(n) == proxy_marker,
            )

            assert guard_lineno is not None, (
                f"{fixture.__name__} must skip under pytest-xdist before "
                "touching the shared proxy"
            )
            assert yield_lineno is None or guard_lineno < yield_lineno, (
                f"{fixture.__name__} must guard before yielding the proxy"
            )
            assert proxy_lineno is not None, (
                f"{fixture.__name__} source must contain the expected "
                f"proxy-touching call {proxy_marker!r}"
            )
            assert guard_lineno < proxy_lineno, (
                f"{fixture.__name__} must guard before touching the shared "
                f"proxy ({proxy_marker!r})"
            )


# ---------------------------------------------------------------------------
# tenant_client event-bus singleton race (fixture-resolution-order hazard)
# ---------------------------------------------------------------------------


class TestTenantClientEventBusRace:
    """Regression test for the ``tenant_client`` event-bus rebind hazard.

    ``event_deps._event_bus`` is a module-level singleton. ``tenant_client``
    needs it bound to ``test_redis`` (db=14), but a fixture that transitively
    depends on ``client`` (e.g. an auth login) can resolve AFTER the last
    ``event_deps._event_bus = None`` clear point and re-cache the singleton
    against the ``client`` fixture's own ``FakeRedis``-backed bus. Trusting
    ``is None`` alone to decide whether to rebuild is therefore
    order-dependent and unsound.

    The fix must reject that FakeRedis-bound hazard bus (Finding A) while
    still trusting a real-Redis-backed bus that is not ``test_redis`` by
    *object identity* but IS bound to the same logical DB — a distinct
    real-Redis pool targeting the same worker-scoped DB (e.g. a fixture
    other than the one that built ``test_redis``) must not be discarded
    just because it isn't the same object. Conversely, a real-Redis-backed
    bus bound to a genuinely DIFFERENT
    logical DB than ``test_redis`` must be rebuilt, not trusted — trusting
    it defeats the isolation this fixture exists to provide (a Guardian
    Angel/Codex reviewer finding: a real-but-wrong-DB bus was previously
    trusted unconditionally).

    This exercises ``tests.conftest._rebind_event_bus_if_stale`` directly —
    the exact type/DB-index-check unit ``tenant_client``'s
    ``override_get_event_bus`` delegates to — with fake and real-but-local
    redis clients, no real fixture interleaving and no network I/O (the
    real ``redis.asyncio.Redis`` instances below only construct a
    connection pool and read its ``connection_kwargs``; they never
    connect).
    """

    @staticmethod
    def _make_fake_event_bus(redis_client: object) -> object:
        from app.event_bus import EventBus

        return EventBus(redis_client)

    def test_rebuilds_when_cached_bus_bound_to_fake_redis(self):
        from fakeredis.aioredis import FakeRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        fake_redis = FakeRedis(decode_responses=True)  # the client fixture's hazard bus
        test_redis = object()  # stands in for test_redis (db=14)

        stale_bus = self._make_fake_event_bus(fake_redis)
        assert stale_bus._redis is fake_redis  # sanity: pre-seeded with FakeRedis

        rebuilt = _rebind_event_bus_if_stale(stale_bus, test_redis, EventBus)

        assert rebuilt is not stale_bus, (
            "a bus cached against a FakeRedis client must be rebuilt, "
            "not reused, even though it was not None"
        )
        assert rebuilt._redis is test_redis

    def test_reuses_cached_bus_already_bound_to_test_redis(self):
        # The "reuse the same instance across a request lifecycle" guarantee
        # must be preserved: TestEventsSpy's monkeypatch of bus.publish has
        # to stay attached to the instance the route handler actually uses.
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14)
        correctly_bound_bus = self._make_fake_event_bus(test_redis)

        result = _rebind_event_bus_if_stale(correctly_bound_bus, test_redis, EventBus)

        assert result is correctly_bound_bus

    def test_reuses_cached_bus_bound_to_same_db_different_pool_object(self):
        # DB-INDEX comparison, not object identity, is what must decide
        # trust: a real-Redis pool built independently of test_redis (e.g.
        # the app's own settings pool from ``get_redis_client()``) can
        # still target the SAME worker-scoped DB as test_redis under
        # xdist. That bus must still be trusted and reused, not
        # discarded, so a monkeypatched ``publish`` stays attached to the
        # instance the route handler uses.
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14)
        same_db_different_pool = RealAsyncRedis(host="localhost", port=6379, db=14)
        spied_bus = self._make_fake_event_bus(same_db_different_pool)

        result = _rebind_event_bus_if_stale(spied_bus, test_redis, EventBus)

        assert result is spied_bus, (
            "a bus bound to a real Redis client targeting the SAME "
            "logical DB as redis_client must be trusted and reused, "
            "even when it is a different pool object than redis_client"
        )
        assert result._redis is same_db_different_pool
        assert same_db_different_pool is not test_redis  # distinct object, same DB

    def test_rebuilds_cached_bus_bound_to_a_different_real_redis_db(self):
        # The Guardian Angel/Codex reviewer finding this closes: a real-
        # Redis-backed bus bound to a DIFFERENT logical DB than
        # redis_client (e.g. one built via a direct, un-instrumented
        # ``event_deps.get_event_bus()`` call defaulting to
        # ``settings.REDIS_DB``) must no longer be blindly trusted just
        # because it is real Redis — trusting it would let tenant_client
        # publish outside its assigned worker/tenant database. It must be
        # rebuilt against redis_client instead.
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14)
        wrong_db_real_redis = RealAsyncRedis(host="localhost", port=6379, db=15)
        stale_bus = self._make_fake_event_bus(wrong_db_real_redis)

        result = _rebind_event_bus_if_stale(stale_bus, test_redis, EventBus)

        assert result is not stale_bus, (
            "a bus bound to a real Redis client targeting a DIFFERENT "
            "logical DB than redis_client must be rebuilt, not reused, "
            "even though the cached client is real Redis"
        )
        assert result._redis is test_redis

    def test_rebuilds_cached_bus_bound_to_same_db_but_different_host(self):
        # A second Guardian Angel/Codex reviewer finding this closes:
        # matching the DB index alone does not prove it's the same Redis
        # SERVER. Two clients could target db=14 on two different hosts
        # and still pass a DB-only comparison. Comparing the full
        # (host, port, db) triple catches this: same DB number, different
        # host, must still be rebuilt.
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14)
        same_db_wrong_host = RealAsyncRedis(host="other-redis-host", port=6379, db=14)
        stale_bus = self._make_fake_event_bus(same_db_wrong_host)

        result = _rebind_event_bus_if_stale(stale_bus, test_redis, EventBus)

        assert result is not stale_bus, (
            "a bus bound to a real Redis client on a DIFFERENT host than "
            "redis_client must be rebuilt even when the DB index matches"
        )
        assert result._redis is test_redis

    def test_rebuilds_cached_bus_bound_to_same_host_port_db_but_different_password(
        self,
    ):
        # A third Guardian Angel/Codex reviewer finding this closes:
        # matching (host, port, db) alone does not prove it's the SAME
        # authenticated connection. ``tenant_client`` tries an
        # authenticated Redis connection first and falls back to
        # unauthenticated only on ``AuthenticationError`` — so an
        # unauthenticated cached bus and an authenticated ``redis_client``
        # (or vice versa) can share host/port/db while carrying different
        # credentials. Trusting that cached bus would reuse the WRONG
        # credentials for this client's connection.
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14, password="secret")
        same_target_no_auth = RealAsyncRedis(host="localhost", port=6379, db=14)
        stale_bus = self._make_fake_event_bus(same_target_no_auth)

        result = _rebind_event_bus_if_stale(stale_bus, test_redis, EventBus)

        assert result is not stale_bus, (
            "a bus bound to a real Redis client with DIFFERENT credentials "
            "than redis_client must be rebuilt even when host/port/db match"
        )
        assert result._redis is test_redis

    def test_builds_fresh_bus_when_cache_is_none(self):
        from redis.asyncio import Redis as RealAsyncRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        test_redis = RealAsyncRedis(host="localhost", port=6379, db=14)

        result = _rebind_event_bus_if_stale(None, test_redis, EventBus)

        assert isinstance(result, EventBus)
        assert result._redis is test_redis

    def test_rebuilds_fake_redis_bus_even_if_publish_is_instance_patched(self):
        """An instance-patched ``publish`` earns no trust exception.

        A prior version of this function trusted ANY bus whose ``publish``
        had already been instance-patched (``"publish" in vars(bus)``),
        regardless of its Redis client type or bound target — added so
        ``TestEventsSpy`` (``tests/api/test_assets.py``) could monkeypatch
        a leaked ``FakeRedis``-backed bus it fetched via a raw
        ``event_deps.get_event_bus()`` call and still have it survive this
        check. That blanket exception meant a monkeypatched bus bound to
        the WRONG target (any Redis, not just FakeRedis) would silently be
        trusted, defeating the target check for that one case — flagged by
        a Guardian Angel/Codex review.

        ``TestEventsSpy`` now resolves the bus through
        ``tenant_client.app.dependency_overrides[get_event_bus]()`` (the
        exact closure that calls this function) BEFORE monkeypatching, so
        it always gets a bus this function already bound to the correct
        target — it never needs, and no longer gets, an exception here. A
        ``FakeRedis``-bound bus must be rebuilt unconditionally, monkey-
        patched or not.
        """
        from fakeredis.aioredis import FakeRedis

        from app.event_bus import EventBus
        from tests.conftest import _rebind_event_bus_if_stale

        fake_redis = FakeRedis(decode_responses=True)
        test_redis = object()
        spied_bus = self._make_fake_event_bus(fake_redis)

        async def _spy(event, **kwargs):
            return None

        spied_bus.publish = _spy  # instance-level patch, mirrors monkeypatch.setattr

        result = _rebind_event_bus_if_stale(spied_bus, test_redis, EventBus)

        assert result is not spied_bus, (
            "a FakeRedis-bound bus must be rebuilt even if its publish has "
            "already been instance-patched — patched or not earns no trust "
            "exception from the target check"
        )
        assert result._redis is test_redis


# ---------------------------------------------------------------------------
# Original behavior: REDIS_DB env var must be set before app.core imports
# ---------------------------------------------------------------------------


class TestRedisDbEnvPinnedBeforeAppCore:
    def test_redis_db_env_matches_worker_db_under_xdist(self, monkeypatch):
        from tests.conftest import _worker_scoped_redis_db

        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
        # Simulate a worker process without pre-set REDIS_DB and confirm
        # the conftest-provided default resolves to that worker's DB.
        monkeypatch.delenv("REDIS_DB", raising=False)
        expected = _worker_scoped_redis_db("gw1")
        # Re-run the same conftest-side defaulting logic that conftest.py
        # performs at import time, with the worker id fixed to gw1.
        from tests import conftest as ct

        with mock.patch.object(os, "environ", os.environ.copy()):
            os.environ.setdefault("PYTEST_XDIST_WORKER", "gw1")
            os.environ.pop("REDIS_DB", None)
            resolved = ct.redis_db_value()
        assert resolved == expected == 2

    def test_db_default_follows_worker_context(self, monkeypatch):
        # No explicit REDIS_DB: serial runs default to the app-pool db=15;
        # each real xdist worker defaults to its own mapped DB.
        from tests import conftest as ct

        monkeypatch.delenv("REDIS_DB", raising=False)
        expected = ct._worker_scoped_redis_db(os.environ.get("PYTEST_XDIST_WORKER", ""))
        assert ct.redis_db_value() == expected

    def test_worker_db_wins_over_explicit_redis_db_under_xdist(self, monkeypatch):
        # CI (and CI-like shells) export REDIS_DB=15 explicitly. Under xdist
        # the worker mapping MUST win: otherwise every worker resolves the
        # same db=15 (the serial Toxiproxy/app target) and collides.
        from tests import conftest as ct

        monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
        monkeypatch.setenv("REDIS_DB", "15")
        assert ct.redis_db_value() == 2

    def test_serial_env_redis_db_still_wins_explicitly(self, monkeypatch):
        # Serial runs keep honoring an explicit REDIS_DB, whatever it is.
        from tests import conftest as ct

        monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
        monkeypatch.setenv("REDIS_DB", "10")
        assert ct.redis_db_value() == 10

    def test_env_marker_exists_for_app_import_order_guard(self):
        # The conftest must pin REDIS_DB into the environment at import
        # time (before app.core imports), so the app settings and pool
        # bind to the worker DB. There are TWO branches that write it —
        # the serial ``os.environ.setdefault("REDIS_DB", ...)`` (else) and
        # the xdist ``os.environ["REDIS_DB"] = ...`` direct assignment
        # (if) — and only ONE runs at any given invocation, so a guard
        # that only locates the serial branch never verifies the xdist
        # path it claims to protect (a Guardian Angel/Codex reviewer
        # finding). Locate BOTH write sites structurally and assert both
        # precede the first app import.
        import tests.conftest as ct

        source = open(ct.__file__, encoding="utf-8").read()
        lines = source.splitlines()

        def _line_index(predicate) -> int:
            return next(idx for idx, line in enumerate(lines) if predicate(line.strip()))

        serial_write_line = _line_index(
            lambda s: s.startswith('os.environ.setdefault("REDIS_DB"')
        )
        xdist_write_line = _line_index(
            lambda s: s.startswith('os.environ["REDIS_DB"] =')
        )

        def first_app_core_import_line(lines: list[str]) -> int | None:
            for idx, line in enumerate(lines):
                if (
                    line.startswith("from app.core")
                    or line.startswith("import app.core")
                    or line.startswith("from app.")
                ):
                    return idx
            return None

        app_import_line = first_app_core_import_line(lines)
        assert app_import_line is not None, "conftest must import app code"
        assert serial_write_line < app_import_line, (
            "os.environ.setdefault('REDIS_DB', ...) (serial branch) must "
            "execute before any app import so settings/pool bind to the "
            "worker DB"
        )
        assert xdist_write_line < app_import_line, (
            "os.environ['REDIS_DB'] = ... (xdist branch) must execute "
            "before any app import so settings/pool bind to the worker DB"
        )
        # The default resolver must agree with the environment conftest
        # pinned at import time — the effective setting, whatever it is:
        # db=15 by default in serial, any explicit serial REDIS_DB override
        # (e.g. REDIS_DB=10), or this worker's mapped DB under xdist
        # (conftest overwrites the environment in that case).
        assert ct.redis_db_value() == int(os.environ["REDIS_DB"])
