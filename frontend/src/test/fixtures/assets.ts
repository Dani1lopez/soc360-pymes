import type { AssetList, AssetResponse, OwnershipDeclaration } from "@/api/schema";

export function makeAsset(overrides: Partial<AssetResponse> = {}): AssetResponse {
  return {
    id: "00000000-0000-4000-8000-000000000101",
    type: "domain",
    value: "acme-corp.example",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-02T10:30:00Z",
    ...overrides,
  };
}

/** Envelope de `GET /assets/`, que el backend no publica en OpenAPI. */
export function assetList(
  items: AssetResponse[],
  { total = items.length, limit = 20, offset = 0 }: Partial<Omit<AssetList, "items">> = {},
): AssetList {
  return { items, total, limit, offset };
}

/** Declaración de propiedad (H2) de un activo. */
export function makeOwnership(overrides: Partial<OwnershipDeclaration> = {}): OwnershipDeclaration {
  return {
    id: "00000000-0000-4000-8000-000000000201",
    asset_id: "00000000-0000-4000-8000-000000000101",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    method: "declaration",
    status: "verified",
    token: "token-de-ejemplo",
    declared_by_user_id: "00000000-0000-4000-8000-0000000000b1",
    verified_at: "2026-10-03T12:00:00Z",
    resolved_fingerprint: null,
    created_at: "2026-10-03T12:00:00Z",
    updated_at: "2026-10-03T12:00:00Z",
    ...overrides,
  };
}
