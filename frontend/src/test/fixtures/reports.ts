import type { ReportList, ReportResponse } from "@/api/schema";
import { makeAsset } from "./assets";
import { makeUser } from "./auth";

export function makeReport(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    id: "00000000-0000-4000-8000-000000000301",
    tenant_id: makeUser().tenant_id!,
    asset_id: makeAsset().id,
    name: "Informe mensual",
    report_type: "vulnerability",
    status: "pending",
    summary: null,
    report_metadata: null,
    generated_at: null,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-02T10:30:00Z",
    ...overrides,
  };
}

export function reportList(items: ReportResponse[]): ReportList {
  return { items, total: items.length, offset: 0, limit: 20 };
}
