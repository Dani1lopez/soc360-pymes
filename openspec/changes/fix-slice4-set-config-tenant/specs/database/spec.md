# Database Tenant Context Specification

## Purpose

Preservar el contexto transaccional de tenant y el comportamiento RLS, eliminando interpolación SQL en la escritura de GUC.

## Requirements

### Requirement: Tenant context behavior preserved

El sistema MUST mantener la semántica actual de `set_tenant_context`: contexto por transacción, mismas claves GUC, y mismo efecto sobre `current_setting(..., TRUE)` y RLS.

#### Scenario: Tenant request

- GIVEN un `tenant_id` válido y `is_superadmin = false`
- WHEN `set_tenant_context` se ejecuta
- THEN el contexto del tenant queda disponible para la transacción actual
- AND la visibilidad de filas bajo RLS permanece igual que antes

#### Scenario: Superadmin request

- GIVEN `is_superadmin = true`
- WHEN `set_tenant_context` se ejecuta
- THEN el acceso superadmin sigue habilitado igual que hoy
- AND las políticas RLS siguen interpretando `current_setting(..., TRUE)` con la misma semántica

### Requirement: Tenant context writes must be parameterized

El sistema MUST escribir el contexto con SQL parametrizado mediante `set_config` y MUST NOT interpolar `tenant_id` en el texto SQL.

#### Scenario: Normal write

- GIVEN cualquier `tenant_id`
- WHEN se actualiza el contexto
- THEN el SQL ejecutado usa bind parameters
- AND el valor del tenant no aparece concatenado en el string SQL

#### Scenario: Defense in depth

- GIVEN un caller futuro con validación upstream incompleta
- WHEN se actualiza el contexto
- THEN la escritura del tenant context sigue protegida contra inyección SQL

### Requirement: Existing contract must remain unchanged

El sistema MUST conservar el contrato público de `set_tenant_context`, las policies RLS, la semántica de aislamiento por tenant y los call sites actuales.

#### Scenario: Missing tenant for non-superadmin

- GIVEN `is_superadmin = false` y `tenant_id = None`
- WHEN `set_tenant_context` se invoca
- THEN sigue fallando con `ValueError`

#### Scenario: Existing callers

- GIVEN los dependientes actuales de `set_tenant_context`
- WHEN se compila/ejecuta el cambio
- THEN no requieren cambios de firma ni de flujo
