# Tasks: Sanear F1

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~40 |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | direct |
| Chain strategy | single-to-main |

Decisión necesaria antes del apply: No

## Fases

### Phase 1: Índices en el modelo User

- [x] 1.1 Añadir `Index("ix_users_tenant_active", "tenant_id", "is_active")` a `User.__table_args__` en `app/modules/users/models.py`.
- [x] 1.2 Añadir `Index("ix_users_email_lower", func.lower("email"))` a `User.__table_args__` en `app/modules/users/models.py`.
- [x] 1.3 Añadir imports necesarios (`Index`, `func` de sqlalchemy).

### Phase 2: last_login_at en login

- [x] 2.1 Añadir `user.last_login_at = datetime.now(timezone.utc)` en `login()` tras verificación de password exitosa y antes de crear tokens.
- [x] 2.2 Verificar que `datetime` y `timezone` ya están importados en `service.py`.

### Phase 3: Eliminar request_headers muerto

- [x] 3.1 Eliminar `request_headers: dict | None = None` de la firma de `login()` en `app/modules/auth/service.py`.

### Phase 4: Limpiar tests API vacíos

- [x] 4.1 Eliminar `tests/api/test_auth.py`.
- [x] 4.2 Eliminar `tests/api/test_tenants.py`.
- [x] 4.3 Eliminar `tests/api/test_users.py`.

### Phase 5: Corregir aserción débil

- [x] 5.1 Cambiar `assert resp.status_code in (400, 401)` a `assert resp.status_code == 400` en `tests/test_auth.py:189`.

### Phase 6: Verificación

- [x] 6.1 Ejecutar `uv run pytest -m "not integration"` — 336 passed, 106 errors preexistentes (conftest/fixture async loop issue, no relacionados con heal-f1).
- [x] 6.2 Ejecutar `uv run ruff check` — errores F821 preexistentes en string annotations de `EventBus`, no de heal-f1.
- [x] 6.3 Ejecutar `uv run alembic heads` — `bfca7016cbb7 (head)` sin cambios.
- [x] 6.4 Verificar que `uv run pytest tests/unit/test_users.py` pasa (18 passed). `tests/test_auth.py` errores preexistentes.
