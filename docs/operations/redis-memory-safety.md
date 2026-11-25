# Redis memory safety

This service Redis contains security, coordination, event, and forensic state. It is
not a disposable cache. The effective policy is `noeviction`: memory pressure must
produce an observable write failure rather than silently remove a key.

## Environment inputs

`REDIS_MAXMEMORY` is the Redis logical memory boundary. `REDIS_CONTAINER_MEMORY_LIMIT`
is the external/container ceiling. Both are required inputs to `docker-compose.yml`.
They are environment-owned values and must be measured per environment. Values in
`.env.example` are development-representative only, not production sizing. The
isolated pressure fixture uses smaller test-only values and must never be copied to
deployment. Existing local `.env` files need both inputs after this configuration
change.

The container ceiling must leave verified room for allocator fragmentation, Redis
process overhead, client buffers, persistence/fork overhead where applicable, and
runtime safety margin. No fixed ratio or production capacity recommendation is made
here. The shared Redis service remains coupled: event producers and security flows
can still consume the same memory budget. Physical separation is deferred to
`sdd/features/redis-domain-isolation`.

## Evidence capture

Capture these fields before rollout, at pressure, and after recovery:

```text
redis-cli CONFIG GET maxmemory maxmemory-policy
redis-cli INFO memory
redis-cli INFO stats
redis-cli INFO errorstats
docker inspect --format '{{.HostConfig.Memory}}' <redis-container>
```

Record:

- Redis version, environment, image, and workload shape.
- Logical `maxmemory`, enforced container ceiling, and measured overhead context.
- `used_memory`, `used_memory_peak`, and computed headroom (`maxmemory - used_memory`,
  bounded at zero).
- OOM/rejected-write evidence from `errorstat_OOM` and `total_error_replies`.
- `evicted_keys` before and after the observation window.
- `soc360_redis_outages_total{flow}` increase and application/ingress 503 rate where
  available.
- Representative security-state and DLQ metadata checks, without logging secrets,
  tokens, raw payloads, or production endpoints.

Critical conditions are any sustained OOM or rejected-write increase and any increase
in `evicted_keys` after rollout. Warn on low or rapidly declining headroom; calibrate
the numeric threshold from rollout measurements, not from this document.
Correlate Redis-native signals with `rate(soc360_redis_outages_total[5m])` and the
application/access-log 503 rate.

## Pre-rollout gate

Do not proceed until the following evidence is retained:

1. Effective policy is exactly `noeviction`.
2. Logical and external limits are present and match environment-owned inputs.
3. Current memory, peak memory, fragmentation/overhead context, counters, and
   computed headroom are captured.
4. A safe, read-only representative security-state and DLQ metadata check succeeds.
5. Current used memory is below the proposed logical limit, the container ceiling
   exists, and verified overhead fits inside that ceiling.

If any condition fails, hold rollout and resolve capacity without restoring eviction.

## Deployment gate

After restart/configuration and before normal producer load:

- Query `CONFIG GET maxmemory-policy` and require `noeviction`.
- Recheck both limits against the deployment inputs.
- Recapture memory, headroom, OOM, error-reply, and eviction counters.
- Verify representative revoked-token/session, lockout/lock, and DLQ metadata.
- Run a small write/read/delete canary in a dedicated operational namespace, never
  in an `events:dlq:*` stream.
- Compare Redis outage and application 503 rates with the baseline.

## Recovery under insufficient headroom

Keep `noeviction`. Pause or rate-limit nonessential producers where possible.
Within verified host capacity, raise the external limit, then measure overhead before
adjusting logical `maxmemory`. Revalidate both effective values, resume gradually,
and recheck all evidence and representative state.

Forbidden actions are restoring `allkeys-lru`, `volatile-lru`, `volatile-ttl`, or any
evicting policy; disabling the ceiling; bulk-deleting unknown keys; or deleting,
trimming, migrating, rewriting, or making the DLQ durable as pressure relief.

There is no safe rollback to the former eviction policy. A package rollback is safe
only when its resulting configuration still enforces `noeviction` and an external
bound. The durable-DLQ follow-up is `sdd/features/durable-dlq`; active-JTI lifecycle
work is `sdd/features/active-jti-lifecycle`. Those features are not defined here.

## Disposable pressure regression

The final CI gate starts `docker-compose.redis-pressure.yml` under the dedicated
project `soc360-redis-pressure`, verifies a non-zero runtime memory bound, and runs
only `pytest -m redis_pressure`. The fixture is a real Redis container with temporary
representative limits, a loopback-only port, test-only password, and disposable
storage. It never uses the shared Redis, DB 15, Toxiproxy, fakeredis, `FLUSHALL`,
`FLUSHDB`, stream trimming, or seeded-state deletion. CI always tears it down with
`docker compose ... down -v`, including failed runs.

The pressure test seeds revoked-token, active-JTI, rate-limit, distributed-lock, and
DLQ records; fills only run-owned keys until Redis rejects a write; checks the typed
fail-closed error, outage metric, sanitized 503 and `Retry-After`; and verifies all
seeded state plus `evicted_keys == 0`. Recovery deletes only run-owned filler keys
and confirms a representative write and the seeded state again succeed.
