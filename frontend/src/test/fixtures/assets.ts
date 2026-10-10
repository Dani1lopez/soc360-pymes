import type { AssetList, AssetResponse } from "@/api/schema";

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
