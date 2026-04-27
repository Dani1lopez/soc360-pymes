# Proposal: Reemplazar f-string SQL por `set_config` parametrizado

## Intent

Eliminar `f"SET LOCAL app.current_tenant = '{str(tenant_id)}'"` en `set_tenant_context()` (database.py:57). Violación de defensa en profundidad — el tipo `UUID` es guard-rail, no eliminación del vector. Issue #23, Slice 4.

## Scope

### In Scope
- `set_tenant_context`: reemplazar `SET LOCAL` por `SELECT set_config(...)` con bind parameters en ambas ramas (tenant y superadmin)
- Verificar equivalencia RLS con `current_setting`

### Out of Scope
- Validación UUID adicional (redundante)
- Migrar `SET LOCAL` en tests (strings fijos, sin riesgo)
- Cambiar políticas RLS o migraciones

## Capabilities

### New Capabilities
None

### Modified Capabilities
None — cambio interno de implementación. Contrato de `set_tenant_context` no cambia.

## Approach

**Opción 3:** `SELECT set_config('app.current_tenant', :tenant_id, true)` con bind parameters de SQLAlchemy.

```python
# Antes:
text(f"SET LOCAL app.current_tenant = '{str(tenant_id)}'")

# Después:
text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
{"tenant_id": str(tenant_id)}
```

**Por qué gana sobre f-string + validación UUID:**
1. Elimina el vector (no lo atenúa): bind parameter → SQLAlchemy escapa, no hay superficie de inyección.
2. Defensa en profundidad: futuro caller que omita validación sigue protegido.
3. `set_config` es built-in C desde PG 8.0 — cero overhead.
4. `pg_stat_statements` muestra queries limpias, sin concatenación.
5. Ambas ramas usan el mismo patrón → menos superficie cognitiva.

**Equivalencia RLS:** `SET LOCAL` y `set_config(..., true)` escriben el mismo namespace GUC transaccional. `current_setting('app.current_tenant', TRUE)` no distingue cómo se escribió. `missing_ok=true` → NULL si no hay contexto → RLS deniega (sin cambios).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `app/core/database.py:44-65` | Modified | Reemplazar 3 `text()` calls en `set_tenant_context` |
| `app/dependencies.py` | None | `get_db_with_tenant` llama a `set_tenant_context` — sin cambios |
| Tests (97) | Verified | Fixtures usan `SET LOCAL` directo con strings fijos — sin cambios |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `set_config` retorna result set y `execute()` difiere | Low | `execute()` acepta SELECT; result set se ignora |
| Cambio en rama superadmin rompe fixtures | Low | Fixtures usan `SET LOCAL` propio (conftest.py:97), no pasan por `set_tenant_context` |

## Rollback Plan

`git revert` del commit. Cero migraciones, cero cambios de esquema.

## Dependencies

None.

## Success Criteria

- [ ] `set_tenant_context` sin f-strings ni interpolación SQL
- [ ] Ambas ramas usan `set_config` con bind parameters
- [ ] RLS: `current_setting` devuelve mismos valores que antes
- [ ] 97/97 tests pasan sin modificación
