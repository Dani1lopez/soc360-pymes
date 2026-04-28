# Design: Issue 42 — PII raw publicado a Redis

## Technical Approach

Change the data contract of `AuthLoginEvent` so that PII (Personally Identifiable Information) such as `email` and `ip_address` are sanitized *before* being published to Redis. The event consumer will then read these sanitized fields directly, rather than performing the masking after the raw data has already been leaked to the bus.

## Architecture Decisions

### Decision: Sanitization Location

**Choice**: Add `app/core/pii.py` to sanitize fields right before publishing from the `auth/service.py` module.
**Alternatives considered**: Passing raw fields to another internal service, or relying on Redis ACLs.
**Rationale**: Easiest and safest to sanitize data at the edge of the producer so that sensitive data never enters the event bus in the first place. This adheres to privacy-by-design principles.

### Decision: PII Field Renaming

**Choice**: Rename `email` to `email_hash` and `ip_address` to `ip_prefix` in `AuthLoginEvent`.
**Alternatives considered**: Keeping the same field names but storing masked data.
**Rationale**: Renaming prevents type confusion and unambiguously indicates to any developer or downstream consumer that the field contains sanitized data rather than raw PII.

## Data Flow

    auth/service.py ──(sanitize)──> AuthLoginEvent ──(publish)──> Redis Stream
         │                                                            │
         └───────────── (Masked IPs, Hashed Emails) ──────────────────┘
                                                                      │
    auth.login consumer <───────────(consume)─────────────────────────┘
         │
         └───────────── (Logs sanitized data)

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/core/pii.py` | Create | Implements `hash_email()` and `mask_ip()` |
| `app/event_schemas.py` | Modify | Update `AuthLoginEvent`: remove `email`/`ip_address`, add `email_hash`/`ip_prefix` |
| `app/modules/auth/service.py` | Modify | Update `login()` to use PII sanitization functions before creating `AuthLoginEvent` |
| `app/event_bus.py` | Modify | Update `_handle_auth_login` to consume `email_hash` and `ip_prefix` directly |

## Interfaces / Contracts

```python
# app/core/pii.py
def hash_email(email: str | None) -> str | None:
    """Returns SHA256[:16] hex of email, or None."""
    pass

def mask_ip(ip_address: str | None) -> str | None:
    """Returns 'x.x.x.0/24' for IPv4, or None."""
    pass

# app/event_schemas.py
class AuthLoginEvent(BaseEvent):
    ...
    # Removed: email, ip_address
    email_hash: Annotated[str, Field(description="Truncated SHA256 hash of email")]
    ip_prefix: Annotated[str | None, Field(default=None, description="Masked IP subnet (e.g. x.x.x.0/24)")]
    user_agent: Annotated[str | None, Field(default=None, description="Client User-Agent if available")]
```

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `app/core/pii.py` | Validate email hashing returns 16-char hex string, handles `None`. Validate IP masking correctly formats IPv4 to `/24`, handles `None`. |
| Unit | `AuthLoginEvent` model | Update `tests/unit/test_event_schemas.py` and `tests/unit/test_event_schemas_edge_cases.py` to assert `email_hash` and `ip_prefix` fields. |
| Unit | `get_event_bus().publish` | Update `tests/unit/test_auth_service_event_publish.py` to ensure sanitized fields are published. |
| Unit | `EventConsumer` | Update `tests/unit/test_event_bus.py`, `tests/unit/test_event_bus_edge_cases.py`, and `test_event_bus_handler.py` to simulate consumed events with the new schema. |
| Integration | End-to-end login event | Update `tests/integration/test_auth_login_event_flow.py` to verify full flow without PII leaks. |

## Migration / Rollout

No data migration required as Redis Streams are ephemeral and we assume no strict schema validation for historical events. Consumers should tolerate the change or be redeployed simultaneously with producers.

## Open Questions

- None
