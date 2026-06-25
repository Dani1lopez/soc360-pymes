# F2 Domain Models Specification

## Purpose

Persistence schema for F2 security entities with tenant isolation, cascading deletes, and domain constraints.

## Requirements

### Requirement: F2 entity tables

The system MUST provide four tenant-scoped tables: `assets`, `scans`, `vulnerabilities`, and `reports`. Each MUST have a UUID primary key, a non-null `tenant_id` foreign key to `tenants.id` with `ON DELETE CASCADE`, non-null `created_at` and `updated_at`, and the columns and constraints below:

| Table | Columns | Domain constraints |
|---|---|---|
| `assets` | `name`, optional `hostname`, `asset_type`, `status`, optional `asset_metadata` (JSONB) | `asset_type` ∈ {host, domain, ip, web_app}; `status` ∈ {active, inactive, archived}, default active |
| `scans` | `asset_id`, `name`, `scan_type`, `status`, optional `config` (JSONB), optional `started_at`/`completed_at` | `scan_type` ∈ {discovery, vulnerability, web, full}; `status` ∈ {pending, running, completed, failed, cancelled}, default pending |
| `vulnerabilities` | `scan_id`, `title`, optional `description`, `severity`, `status`, optional `cve_id`, optional `cvss_score`, optional `vulnerability_metadata` (JSONB) | `severity` ∈ {critical, high, medium, low, info}; `status` ∈ {open, fixed, accepted_risk, false_positive}, default open |
| `reports` | `asset_id`, `name`, `report_type`, `status`, optional `summary`, optional `report_metadata` (JSONB), optional `generated_at` | `report_type` ∈ {vulnerability, executive, technical, compliance}; `status` ∈ {pending, generating, completed, failed}, default pending |

#### Scenario: Valid asset is persisted

- GIVEN a tenant exists
- WHEN an asset with `asset_type` `host` is inserted
- THEN the row is stored with `status` `active`

#### Scenario: Invalid scan type is rejected

- GIVEN a tenant and asset exist
- WHEN a scan with `scan_type` `other` is inserted
- THEN the insert is rejected

#### Scenario: Vulnerability links to scan

- GIVEN a scan exists
- WHEN a vulnerability is inserted with that `scan_id`
- THEN the row is stored

#### Scenario: Report links to asset

- GIVEN an asset exists
- WHEN a report is inserted with that `asset_id`
- THEN the row is stored

### Requirement: Cascading deletes

The system MUST delete `scans` and `reports` when their `asset` is deleted, `vulnerabilities` when their `scan` is deleted, and all four tables when a `tenant` is deleted.

#### Scenario: Asset deletion cascades

- GIVEN an asset has scans and reports
- WHEN the asset is deleted
- THEN the scans and reports are also deleted

### Requirement: Tenant isolation

The system MUST enforce row-level tenant isolation on the four F2 tables so a non-superadmin session only accesses rows whose `tenant_id` matches the session's current tenant.

#### Scenario: Cross-tenant read is blocked

- GIVEN assets exist for tenants A and B
- WHEN a session scoped to tenant A queries assets
- THEN only tenant A's assets are returned

### Requirement: Query indexes

The system MUST create indexes on `tenant_id` and on each parent foreign-key column.

#### Scenario: Tenant-scoped query is indexed

- GIVEN an F2 table contains rows for many tenants
- WHEN a query filters by `tenant_id`
- THEN the database uses the tenant index
