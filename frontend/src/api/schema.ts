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
