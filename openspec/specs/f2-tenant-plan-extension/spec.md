# F2 Tenant Plan Extension Specification

## Purpose

Extends `tenants` with columns that govern scan frequency, AI enrichment tier, and enabled report types.

## Requirements

### Requirement: Tenant plan columns

The system MUST add these columns to `tenants`:

| Column | Type | Nullable | Default |
|---|---|---|---|
| `scans_per_day` | integer | NO | `1` |
| `ai_enrichment_level` | string (max 50) | NO | `basic` |
| `report_types` | JSONB | YES | `["vulnerability"]` |

#### Scenario: New tenant uses defaults

- GIVEN a tenant is created without plan columns
- WHEN the row is inserted
- THEN `scans_per_day` is `1`, `ai_enrichment_level` is `basic`, and `report_types` is `["vulnerability"]`

### Requirement: Backfill existing tenants

The system MUST set `report_types` to `["vulnerability"]` for every existing tenant whose `report_types` is NULL after the column is added.

#### Scenario: Existing tenant is backfilled

- GIVEN an existing tenant has NULL `report_types`
- WHEN the migration upgrade runs
- THEN the value becomes `["vulnerability"]`

### Requirement: Reversible extension

The system MUST be able to remove the three tenant columns on downgrade.

#### Scenario: Downgrade removes columns

- GIVEN the tenant extension is applied
- WHEN the migration is downgraded by one revision
- THEN the three columns no longer exist
