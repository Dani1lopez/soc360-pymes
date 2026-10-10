import type { components, paths } from "@/api/types";

// Narrow, stable aliases over the generated OpenAPI types (`src/api/types.ts`,
// regenerated with `pnpm gen:api`). Feature code imports from here, never from
// the generated file, so a regeneration only has to be reconciled in one place.
export type ApiPaths = paths;
export type ApiSchemas = components["schemas"];

export type TokenResponse = ApiSchemas["TokenResponse"];
export type UserResponse = ApiSchemas["UserResponse"];
export type Role = ApiSchemas["RoleEnum"];
export type LoginRequest = ApiSchemas["LoginRequest"];
export type Severity = ApiSchemas["VulnerabilityResponse"]["severity"];

/** Envelope every paginated list endpoint shares. */
export type Paginated<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

// Assets. `GET /assets/` shares its path with the CSV export and answers with
// `response_model=None`, so the OpenAPI snapshot does not describe its shape;
// the envelope is declared here from the backend contract
// (`app/modules/assets/schemas.py::AssetListResponse`).
export type AssetResponse = ApiSchemas["AssetResponse"];
export type AssetType = AssetResponse["type"];
export type AssetList = Paginated<AssetResponse>;
export type AssetUpdateInput = ApiSchemas["AssetUpdate"];
export type AssetCreateInput =
  ApiPaths["/api/v1/assets/"]["post"]["requestBody"]["content"]["application/json"];

// Scans. `POST /scans/` is a discriminated union on `type`, and `PATCH` accepts
// the name, the type and a config object that the backend validates against the
// resulting type.
//
// `config` is declared as `object | null` in FastAPI, which `openapi-typescript`
// renders as `Record<string, never>`: a type no real payload can satisfy. The
// two aliases below widen it back to a JSON object, with the field names the
// backend validates per scan type.
export type ScanConfig = Record<string, unknown>;
export type ScanResponse = Omit<ApiSchemas["ScanResponse"], "config"> & {
  config: ScanConfig | null;
};
export type ScanType = ScanResponse["type"];
export type ScanStatus = ScanResponse["status"];
export type ScanList = Paginated<ScanResponse>;
export type ScanUpdateInput = Omit<ApiSchemas["ScanUpdate"], "config"> & {
  config?: ScanConfig | null;
};
export type ScanCreateInput =
  ApiPaths["/api/v1/scans/"]["post"]["requestBody"]["content"]["application/json"];

// Vulnerabilities and enrichment. `vulnerability_metadata` is `object | null` in
// FastAPI, so the generator renders it as `Record<string, never>`; the aliases
// below widen it (see the scans note above).
export type VulnerabilityStatus = ApiSchemas["VulnerabilityResponse"]["status"];
export type VulnerabilityResponse = Omit<
  ApiSchemas["VulnerabilityResponse"],
  "vulnerability_metadata"
> & { vulnerability_metadata: Record<string, unknown> | null };
export type VulnerabilityList = Paginated<VulnerabilityResponse>;
export type VulnerabilityCreateInput = Omit<
  ApiSchemas["VulnerabilityCreate"],
  "vulnerability_metadata"
> & { vulnerability_metadata?: Record<string, unknown> | null };
export type VulnerabilityUpdateInput = Omit<
  ApiSchemas["VulnerabilityUpdate"],
  "vulnerability_metadata"
> & { vulnerability_metadata?: Record<string, unknown> | null };

/**
 * Enrichment. `GET /vulnerabilities/{id}/enrichment` returns one item per
 * function of the tenant's level; `POST` on the vulnerability or on the scan
 * only queues work and answers with how much was queued.
 */
export type EnrichmentItem = ApiSchemas["EnrichmentItemRead"];
export type VulnerabilityEnrichment = ApiSchemas["VulnerabilityEnrichmentRead"];
export type EnrichmentQueued = ApiSchemas["EnrichmentQueued"];
export type ScanEnrichmentQueued = ApiSchemas["ScanEnrichmentQueued"];

// Dashboard. One call per tenant returns the four metrics and the 30-day trend.
export type DashboardSummary = ApiSchemas["DashboardSummary"];
export type SeverityCounts = ApiSchemas["SeverityCounts"];
export type TrendDay = ApiSchemas["TrendDay"];
export type CoverageMetric = ApiSchemas["CoverageMetric"];
export type ScanSuccessMetric = ApiSchemas["ScanSuccessMetric"];

// Reports. Metadata only: there is no PDF generation in this phase (D9), and
// `report_metadata` is another `object | null` that needs widening.
export type ReportType = ApiSchemas["ReportResponse"]["report_type"];
export type ReportStatus = ApiSchemas["ReportResponse"]["status"];
export type ReportResponse = Omit<ApiSchemas["ReportResponse"], "report_metadata"> & {
  report_metadata: Record<string, unknown> | null;
};
export type ReportList = Paginated<ReportResponse>;
export type ReportCreateInput = Omit<ApiSchemas["ReportCreate"], "report_metadata"> & {
  report_metadata?: Record<string, unknown> | null;
};
export type ReportUpdateInput = Omit<ApiSchemas["ReportUpdate"], "report_metadata"> & {
  report_metadata?: Record<string, unknown> | null;
};

// Administration. `GET /users/` and `GET /tenants/` answer with a plain array
// (no pagination envelope), unlike every other list in the API.
export type UserCreateInput = ApiSchemas["UserCreate"];
export type UserUpdateInput = ApiSchemas["UserUpdate"];
export type TenantResponse = ApiSchemas["TenantResponse"];
export type TenantSettings = ApiSchemas["TenantSettings"];
export type TenantUpdateInput = ApiSchemas["TenantUpdate"];
export type ChangePasswordInput = ApiSchemas["ChangePasswordRequest"];
