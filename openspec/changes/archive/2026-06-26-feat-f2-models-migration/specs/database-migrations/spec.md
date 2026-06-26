# Delta for Database Migrations

## MODIFIED Requirements

### Requirement: F2 schema revisions

The system MUST provide two chained migration revisions, R1 and R2, that follow the current main head `b5e9d8c4a123` and leave `alembic heads` with a single head after each revision.
(Previously: a single migration revision followed the main head.)

#### Scenario: R1 chains to main head

- GIVEN the database is at revision `b5e9d8c4a123`
- WHEN R1 is applied
- THEN `alembic heads` reports one head

#### Scenario: R2 chains to R1

- GIVEN the database is at revision R1
- WHEN R2 is applied
- THEN `alembic heads` reports one head

### Requirement: Upgrade creates schema objects in two stages

The system MUST split schema creation across R1 and R2: R1 creates the `assets` and `scans` tables and adds the three tenant plan columns with backfill; R2 creates the `vulnerabilities` and `reports` tables. Each revision MUST create columns, constraints, indexes, row-level security policies, updated-at triggers, and grants for the tables it owns.
(Previously: one revision created all four tables and tenant columns.)

#### Scenario: R1 upgrade succeeds

- GIVEN a database at the previous main head
- WHEN the R1 upgrade runs
- THEN `assets`, `scans`, the three tenant columns, indexes, and policies exist
- AND `vulnerabilities` and `reports` do not exist

#### Scenario: R2 upgrade succeeds

- GIVEN a database at revision R1
- WHEN the R2 upgrade runs
- THEN `vulnerabilities` and `reports`, their indexes, and policies exist

### Requirement: Downgrade reverses each stage

The system MUST, on downgrade, reverse only the schema objects created by the target revision: R1 downgrade drops `assets`, `scans`, and the three tenant columns; R2 downgrade drops `vulnerabilities` and `reports`. Each downgrade MUST remove policies, revoke grants, drop indexes and triggers, and return to the previous revision.
(Previously: one downgrade reversed all four tables and tenant columns.)

#### Scenario: R2 downgrade reverses PR-B

- GIVEN R2 is applied
- WHEN the migration is downgraded by one revision
- THEN `vulnerabilities` and `reports` no longer exist and R1 is restored

#### Scenario: R1 downgrade reverses PR-A

- GIVEN R1 is applied
- WHEN the migration is downgraded by one revision
- THEN `assets`, `scans`, and the three tenant columns no longer exist and the previous main head is restored

## ADDED Requirements

### Requirement: Migration environment registers models per PR

The system MUST register only the model modules relevant to each PR in the migration environment: PR-A registers `assets` and `scans`; PR-B registers `vulnerabilities` and `reports`.

#### Scenario: PR-A autogenerate includes R1 models

- GIVEN the migration environment imports `assets` and `scans`
- WHEN an autogenerate revision is created on PR-A
- THEN `assets` and `scans` are not flagged as missing

#### Scenario: PR-B autogenerate includes R2 models

- GIVEN the migration environment imports `vulnerabilities` and `reports`
- WHEN an autogenerate revision is created on PR-B
- THEN `vulnerabilities` and `reports` are not flagged as missing
