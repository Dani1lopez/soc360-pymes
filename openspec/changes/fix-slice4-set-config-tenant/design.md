# Design: Reemplazar f-string SQL por `set_config` parametrizado

## Technical Approach

Reemplazar los tres `text()` interpolados en `set_tenant_context` por `SELECT set_config(...)` con bind parameters de SQLAlchemy. Ambas ramas (superadmin y tenant) usan el mismo patrón para reducir superficie cognitiva. `set_config(..., true)` escribe en el namespace GUC transaccional, equivalente a `SET LOCAL`. `current_setting('app.current_tenant', TRUE)` no distingue el método de escritura, por lo que RLS sigue funcionando idénticamente.

## Architecture Decisions

| Decision | Alternativa | Rationale |
|----------|-------------|-----------|
| Usar `SELECT set_config('var', :val, true)` con bind params | Validar UUID y seguir con f-string | Elimina el vector de inyección en lugar de atenuarlo. Defensa en profundidad para futuros callers. |
| Aplicar el patrón también a `app.is_superadmin` | Solo cambiar `app.current_tenant` | Menos superficie cognitiva; ambas ramas se ven igual. Cero costo de performance (`set_config` es built-in C). |
| No modificar tests existentes (97) | Refactorizar fixtures a `set_config` | Los fixtures usan strings UUID fijos hardcodeados (sin superficie de inyección). Cambiarlos no aporta seguridad y aumenta el diff. |
| Crear test unitario nuevo para `set_tenant_context` | Confiar solo en tests de integración | Necesitamos evidencia directa de que el query string no contiene interpolación y que los parámetros se pasan correctamente. |

## Data Flow

```
get_db_with_tenant()
        │
        ▼
set_tenant_context(db, tenant_id, is_superadmin)
        │
        ├── rama superadmin ──► db.execute("SELECT set_config('app.is_superadmin', 'true', true)")
        │
        └── rama tenant ──────► db.execute("SELECT set_config('app.current_tenant', :tenant_id, true)", {"tenant_id": str(tenant_id)})
                                db.execute("SELECT set_config('app.is_superadmin', 'false', true)")
        │
        ▼
RLS policies leen vía current_setting('app.current_tenant', TRUE)
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/core/database.py` | Modify | Reemplazar 3 `text()` calls en `set_tenant_context` por `SELECT set_config(...)` con bind params. |
| `tests/unit/test_database.py` | Create | Test unitario que mockea `db.execute` y asserta que no hay f-strings ni interpolación. |

## Interfaces / Contracts

`set_tenant_context(db, tenant_id, is_superadmin)` no cambia su firma ni su semántica externa. Es un cambio de implementación interno puro.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `set_tenant_context` usa bind params | Mock de `AsyncSession.execute`; assert sobre `call_args` verificando que el string no contiene `'` alrededor del placeholder y que `parameters` incluye `"tenant_id"`. |
| Integration | Equivalencia RLS | Llamar a `set_tenant_context` con un tenant_id conocido, luego `SELECT current_setting('app.current_tenant', TRUE)` y assertar igualdad. |
| E2E | Regresión de aislamiento | Correr suite completa (97 tests). Los tests `test_rls_admin_a_cannot_see_tenant_b_data` y similares ya ejercitan el camino feliz. |

## Migration / Rollout

No migration required. `git revert` del commit revierte al estado anterior sin migraciones ni cambios de esquema.

## Open Questions

- [ ] None
