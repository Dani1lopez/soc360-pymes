# Design: Sanear F1

## Technical Approach

Cambios quirúrgicos en archivos existentes. Sin migraciones nuevas. Sin nuevas dependencias. Sin refactorización.

## Decisiones de Diseño

### D-001: Índices como `Index` objects en `__table_args__`

Los índices se declaran usando `sqlalchemy.Index` con `postgresql_using="btree"` (default). Para el índice funcional `ix_users_email_lower`, se usa `func.lower(User.email)` vía `sa.text`.

```python
from sqlalchemy import Index, func

__table_args__ = (
    CheckConstraint(...),
    # ... existing constraints ...
    Index("ix_users_tenant_active", "tenant_id", "is_active"),
    Index("ix_users_email_lower", func.lower("email")),
)
```

**Nota**: `ix_users_email_lower` usa `func.lower("email")` con string literal porque `func.lower(User.email)` causaría un error de importación circular al evaluarse en el nivel de clase. El nombre de columna como string es válido en SQLAlchemy para definiciones de `Index` dentro de `__table_args__`.

### D-002: last_login_at en login()

Después de la autenticación exitosa (password verificado, tenant activo), pero antes de crear tokens:

```python
user.last_login_at = datetime.now(timezone.utc)
```

El `db.flush()` ya existe para la creación del refresh token, así que no se necesita flush adicional.

### D-003: Eliminar request_headers

Se elimina `request_headers: dict | None = None` de la firma de `login()` en `app/modules/auth/service.py`. 

El router (`app/modules/auth/router.py`) ya NO pasa este parámetro (línea 52-58), así que no hay cambios en el router.

### D-004: Archivos vacíos

Eliminar físicamente:
- `tests/api/test_auth.py`
- `tests/api/test_tenants.py`
- `tests/api/test_users.py`

Los 3 archivos tienen 0 líneas. El `__init__.py` de `tests/api/` se conserva.

### D-005: Corregir aserción

En `tests/test_auth.py:189`:
```python
# Antes
assert resp.status_code in (400, 401)
# Después
assert resp.status_code == 400
```

El servicio `change_password` devuelve 400 para contraseña actual incorrecta (verificado en `app/modules/auth/service.py:399`).

### D-006: Rate Limiting y CSRF — Revisión

**Rate Limiting (Login)**:
- Implementado vía Redis en `_check_account_lockout()` / `_record_failed_attempt()` / `_clear_login_attempts()`
- 10 intentos máximos en ventana de 900 segundos (15 min)
- Fail-closed: si Redis no responde, se niega el acceso
- Respuesta pública siempre 401 (no revela si la cuenta existe)

**CSRF Protection**:
- Cookies de refresh token: `httponly=True`, `samesite="strict"`, `secure=True` (en producción)
- `SecurityHeadersMiddleware`: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `CSP: default-src 'self'`
- `HTTPSRedirectMiddleware`: redirige HTTP → HTTPS en producción

**Veredicto**: La protección actual es adecuada para F1. No se requieren cambios.

## Archivos Modificados

| Archivo | Cambio |
|---------|--------|
| `app/modules/users/models.py` | Añadir 2 `Index` en `__table_args__` |
| `app/modules/auth/service.py` | Añadir `last_login_at` update; eliminar `request_headers` |
| `tests/test_auth.py` | Corregir aserción línea 189 |
| `tests/api/test_auth.py` | ELIMINAR (vacío) |
| `tests/api/test_tenants.py` | ELIMINAR (vacío) |
| `tests/api/test_users.py` | ELIMINAR (vacío) |

## Coherencia con el proyecto

- Sin migraciones nuevas (índices ya existen en DB)
- Sin cambios en dependencias
- Sin nuevos imports (excepto `Index` y `func` de SQLAlchemy que ya es dependencia)
- Patrones consistentes con el resto del código F1
