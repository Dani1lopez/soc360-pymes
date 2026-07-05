# Propuesta: Sanear F1 — Cerrar F1 antes de construir F2

## Intención

Cerrar el 15% restante de F1 resolviendo issues conocidos y acotados antes de arrancar la construcción vertical de F2. El objetivo no es refactorizar F1 entero, sino sanear lo estrictamente necesario para declarar F1 cerrado.

## Alcance

### In Scope

| # | Issue | Severidad |
|---|-------|-----------|
| 1 | Añadir `Index` definitions en el modelo `User` para `ix_users_email_lower` y `ix_users_tenant_active` — los índices existen en la DB vía migraciones manuales pero no están declarados en el modelo SQLAlchemy, por lo que un autogenerate futuro los eliminaría | Alta |
| 2 | Actualizar `last_login_at` en la función `login()` — la columna existe en el modelo y la migración, pero nunca se escribe | Media |
| 3 | Eliminar parámetro muerto `request_headers` de `service.login()` — no se usa en el cuerpo de la función ni lo pasa el router | Baja |
| 4 | Eliminar archivos vacíos `tests/api/test_auth.py`, `tests/api/test_tenants.py`, `tests/api/test_users.py` (0 líneas cada uno) | Baja |
| 5 | Corregir aserción débil en `tests/test_auth.py:189` — `assert resp.status_code in (400, 401)` debe ser `== 400` (el servicio devuelve 400 para contraseña incorrecta) | Media |
| 6 | Revisar rate limiting y CSRF — verificar que la protección actual (login lockout vía Redis + cookies `samesite:strict` + security headers) es adecuada y documentarlo | Baja |

### Out of Scope
- Refactorización general de F1
- Nuevas features de F1
- Cambios en F2
- Migraciones nuevas (los índices ya existen en la DB, solo se declaran en el modelo)
- Reescritura de tests existentes (solo se corrigen aserciones)

## Capabilities

### Modified Capabilities
- **F1 Auth**: `last_login_at` se actualiza en login, `request_headers` eliminado
- **F1 Users Model**: índices declarados en `__table_args__`
- **F1 Tests**: archivos vacíos eliminados, aserción débil corregida

### New Capabilities
- Ninguna

## Approach

1. Añadir `Index` definitions al modelo `User.__table_args__`
2. Añadir `user.last_login_at = datetime.now(timezone.utc)` en `login()` tras autenticación exitosa
3. Eliminar `request_headers` de la firma de `login()`
4. Eliminar los 3 archivos de tests API vacíos
5. Corregir `assert resp.status_code in (400, 401)` → `assert resp.status_code == 400`
6. Documentar el estado de rate limiting y CSRF en el design

## Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Añadir índices al modelo cambie el comportamiento de Alembic autogenerate | Verificar que los índices ya existen en la DB actual; solo es declarativo |
| Eliminar `request_headers` rompa callers externos | Verificar que ningún caller lo pasa (router no lo usa, ni tests) |

## Rollback

Revertir el commit. Sin migraciones nuevas que deshacer.

## Criterios de Éxito

- [ ] `Index` definitions presentes en `User.__table_args__`
- [ ] `last_login_at` se actualiza en cada login exitoso
- [ ] `request_headers` eliminado de `service.login()`
- [ ] Archivos de tests API vacíos eliminados
- [ ] Aserción de `test_change_password_wrong_current` corregida a `== 400`
- [ ] `uv run pytest -m "not integration"` sigue verde
- [ ] `uv run ruff check` limpio en archivos modificados
- [ ] `uv run alembic heads` reporta una sola cabeza sin cambios
