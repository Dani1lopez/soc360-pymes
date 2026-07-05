# Delta Specs — PRD v1 MVP Junio

## Capability: Vulnerable Target Environment

### [REQ-VTE-001] Isolated vulnerable demo target
**Priority**: must-have
**Description**: System MUST provide restartable demo container exposing vsftpd 2.3.4, old OpenSSH, Apache 2.2.8, and MySQL 5.0 on isolated internal network with health checks.
**Acceptance Criteria**:
- [ ] Container starts only on isolated demo network.
- [ ] Health status shows service availability.
- [ ] Restart restores vulnerable services.

#### Scenario: Container starts healthy
**Given** demo stack is deployed
**When** vulnerable target starts
**Then** all required insecure services are reachable and container reports healthy

#### Scenario: Container recovers after restart
**Given** vulnerable target is running
**When** operator restarts it
**Then** service endpoints return to healthy state without joining public network

## Capability: Asset Management

### [REQ-AST-001] Tenant-scoped asset CRUD
**Priority**: must-have
**Description**: API MUST support CRUD for IP and Dominio assets, enforce tenant isolation via RLS, store active/inactive status, and reject writes beyond tenant max_assets.

#### Scenario: Asset created within plan limit
**Given** tenant is below max_assets
**When** admin creates valid IP asset
**Then** asset is stored in same tenant scope with active status by default

#### Scenario: Creation blocked by plan limit
**Given** tenant reached max_assets
**When** admin creates another asset
**Then** API rejects request with plan-limit error and no asset is added

### [REQ-AST-002] Asset format validation
**Priority**: must-have
**Description**: System MUST validate IP and Dominio formats before persistence.

#### Scenario: Invalid IP rejected
**Given** admin submits malformed IP
**When** asset is created or updated
**Then** API returns validation error

#### Scenario: Valid domain accepted
**Given** admin submits valid Dominio
**When** asset is created
**Then** asset is persisted with normalized domain value

## Capability: Scan Engine

### [REQ-SCN-001] Manual and scheduled scans
**Priority**: must-have
**Description**: System MUST allow POST /assets/{id}/scans manual trigger and recurring per-asset schedules, with lifecycle pending→running→completed/failed, timeout per asset, XML storage, and history.

#### Scenario: Manual scan completes
**Given** asset exists and user can scan it
**When** POST /assets/{id}/scans is called
**Then** scan moves through lifecycle and stores Nmap XML on completion

#### Scenario: Scan times out
**Given** asset has timeout configured
**When** scan exceeds timeout
**Then** scan ends failed with timeout reason and remains in asset history

## Capability: Vulnerability Management

### [REQ-VUL-001] Vulnerability workflow and dedup
**Priority**: must-have
**Description**: System MUST CRUD vulnerabilities, deduplicate by SHA-256(asset_id|vuln_type|port|cve|cwe|path), and support status flow open→acknowledged→resolved/accepted_risk/false_positive.

#### Scenario: Duplicate finding updates existing vuln
**Given** fingerprint already exists
**When** same finding is persisted again
**Then** system updates existing vulnerability instead of creating duplicate

#### Scenario: Status transitions to accepted risk
**Given** analyst sees open vulnerability
**When** analyst marks accepted_risk
**Then** status changes and audit data is stored

### [REQ-VUL-002] RBAC and filtered listing
**Priority**: must-have
**Description**: Viewer MUST be read-only; analyst MUST transition statuses; vulnerability lists MUST filter by severity, status, asset, and date range.

#### Scenario: Viewer blocked from status change
**Given** viewer is authenticated
**When** viewer patches vulnerability status
**Then** API returns forbidden

#### Scenario: Analyst filters critical vulns by asset and date
**Given** tenant has mixed findings
**When** analyst applies severity, asset, and date filters
**Then** only matching vulnerabilities are returned

## Capability: AI Enrichment Pipeline

### [REQ-AI-001] LangGraph enrichment contract
**Priority**: must-have
**Description**: System MUST execute scan→parse XML→AI enrichment→dedup→persist pipeline using existing get_llm_provider abstraction; enrichment MUST classify severity, detect CVEs, generate Spanish description, remediation, CVSS, executive text, priority, and step-by-step instructions.

#### Scenario: Enrichment succeeds
**Given** completed scan XML exists
**When** pipeline runs successfully
**Then** enriched findings include all required AI fields and persist after dedup

#### Scenario: AI retry exhausted
**Given** AI enrichment fails twice
**When** retry limit is reached
**Then** finding is marked needs_ai_retry=true and notification is emitted

## Capability: Dashboard API

### [REQ-DSH-001] Tenant metrics and plan gating
**Priority**: must-have
**Description**: API MUST expose the 10 dashboard metrics tenant-scoped; free gets basic subset, pro full tenant metrics, enterprise full plus cross-tenant access for superadmin.

#### Scenario: Pro tenant reads full metrics
**Given** pro tenant has data
**When** dashboard endpoints are requested
**Then** all tenant-scoped metrics return successfully

#### Scenario: Free tenant blocked from gated metric
**Given** free tenant requests top-10 CVEs
**When** endpoint is called
**Then** API returns plan-gated response

## Capability: Report Generation

### [REQ-RPT-001] Async PDF reporting
**Priority**: must-have
**Description**: System MUST generate asset, global monthly, and scan PDFs asynchronously via ReportLab, expose generating/ready/failed status, support download when ready, and store files with expiry.

#### Scenario: Asset report ready for download
**Given** asset report job completes
**When** user requests report list and download
**Then** status is ready and PDF downloads successfully

#### Scenario: Expired report unavailable
**Given** report file passed expiry
**When** user requests download
**Then** API returns unavailable/expired response

### [REQ-RPT-002] Executive reporting content
**Priority**: must-have
**Description**: Asset report MUST include technical detail plus executive summary in plain Spanish for PyME owner, including risk explanation and exactly 3 remediation steps.

#### Scenario: Asset report contains executive summary
**Given** report is generated for asset with findings
**When** PDF content is inspected
**Then** plain-language risk summary and 3 remediation steps are present

#### Scenario: Scan report separates new and closed findings
**Given** current and prior scan data exist
**When** scan report is generated
**Then** findings are grouped into new and previously closed sections

## Capability: Plan Enforcement

### [REQ-PLN-001] Tenant limit enforcement
**Priority**: must-have
**Description**: Tenant record MUST store max_assets, scans_per_day, ai_enrichment_level, and report_types; API and services MUST enforce those limits consistently.

#### Scenario: Scan quota exceeded
**Given** tenant used scans_per_day quota
**When** another scan is requested
**Then** API rejects request with plan-limit response

#### Scenario: Basic AI level omits premium enrichment
**Given** tenant has basic ai_enrichment_level
**When** enrichment runs
**Then** premium-only enrichment output is not promised or exposed

### [REQ-PLN-002] Plan comparison endpoint
**Priority**: nice-to-have
**Description**: API SHOULD provide plan comparison data for frontend upgrade flows.

#### Scenario: Frontend loads upgrade options
**Given** tenant is on free plan
**When** comparison endpoint is requested
**Then** response shows current limits and higher-plan deltas

## Capability: Event Bus Expansion

### [REQ-EVT-001] Security domain event publication
**Priority**: must-have
**Description**: Existing Redis Streams EventBus MUST publish scan.started, scan.completed, scan.failed, vuln.created, and vuln.updated without removing auth.login behavior.

#### Scenario: Scan completed event emitted
**Given** scan finishes successfully
**When** completion is persisted
**Then** scan.completed event is published

#### Scenario: Existing auth event preserved
**Given** user logs in successfully
**When** auth flow completes
**Then** auth.login event still publishes unchanged

## Capability: Frontend Shell

### [REQ-FE-001] MVP frontend shell and accessibility
**Priority**: must-have
**Description**: Frontend MUST provide 8 pages using React 18, TypeScript, Vite, TanStack Query/Router, react-i18next, WCAG 2.1 AA, token auto-refresh, and virtualized lists.

#### Scenario: Authenticated user navigates shell
**Given** valid session exists
**When** user navigates among pages
**Then** protected routes load without requiring re-login

#### Scenario: Long vulnerabilities list stays usable
**Given** tenant has large vulnerability dataset
**When** user opens Vulnerabilities page
**Then** list remains performant and keyboard-accessible

## Capability: API Completeness

### [REQ-API-001] Complete MVP endpoint surface
**Priority**: must-have
**Description**: Backend MUST expose all MVP routes with auth, tenant scope, and plan gates.

#### Scenario: Asset detail route returns tenant asset
**Given** asset belongs to caller tenant
**When** GET /assets/{id} is requested
**Then** API returns asset detail

#### Scenario: Cross-tenant resource is hidden
**Given** asset belongs to different tenant
**When** caller requests its route
**Then** API returns not found or forbidden per security policy
