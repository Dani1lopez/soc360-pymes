import type { DashboardSummary, TrendDay } from "@/api/schema";

/** 30 días de tendencia, con `opened` creciendo y `closed` apareciendo al final. */
export function makeTrend(overrides: Partial<TrendDay>[] = []): TrendDay[] {
  return Array.from({ length: 30 }, (_, index) => {
    const day = String(index + 1).padStart(2, "0");
    const override = overrides[index];
    return {
      day: `2026-09-${day}`.slice(0, 10),
      opened: index % 5 === 0 ? 2 : 0,
      closed: index > 25 ? 1 : 0,
      ...override,
    };
  });
}

export function makeDashboardSummary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    assets_monitored: 5,
    open_by_severity: { critical: 2, high: 3, medium: 3, low: 1, info: 2 },
    coverage_24h: {
      covered: 2,
      total: 5,
      ratio: 0.4,
      since: "2026-10-09T15:00:00Z",
    },
    scan_success_30d: {
      completed: 5,
      failed: 1,
      ratio: 0.8333,
      since: "2026-09-10T15:00:00Z",
    },
    trend_30d: makeTrend(),
    generated_at: "2026-10-10T15:55:00Z",
    ...overrides,
  };
}
