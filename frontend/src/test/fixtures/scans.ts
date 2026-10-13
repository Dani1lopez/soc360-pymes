import type { ScanList, ScanResponse } from "@/api/schema";

export function makeScan(overrides: Partial<ScanResponse> = {}): ScanResponse {
  return {
    id: "00000000-0000-4000-8000-000000000201",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    asset_id: "00000000-0000-4000-8000-000000000101",
    name: "Descubrimiento de la red interna",
    type: "discovery",
    status: "completed",
    config: { host_discovery: true },
    started_at: "2026-10-09T07:00:00Z",
    completed_at: "2026-10-09T07:01:00Z",
    created_at: "2026-10-09T06:59:00Z",
    updated_at: "2026-10-09T07:01:00Z",
    ...overrides,
  };
}

export function scanList(
  items: ScanResponse[],
  { total = items.length, limit = 20, offset = 0 }: Partial<Omit<ScanList, "items">> = {},
): ScanList {
  return { items, total, limit, offset };
}
