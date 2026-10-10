import { describe, expect, it } from "vitest";
import { makeDashboardSummary, makeTrend } from "@/test/fixtures/dashboard";
import {
  SEVERITY_ORDER,
  criticalOpen,
  hasAnyData,
  severitySeries,
  totalOpen,
  trendLabel,
  trendSeries,
  trendTotals,
} from "./dashboard-metrics";

describe("severitySeries", () => {
  it("keeps the order, labels and tokens of every severity", () => {
    const series = severitySeries({ critical: 2, high: 0, medium: 1, low: 0, info: 3 });

    expect(series.map((datum) => datum.severity)).toEqual([...SEVERITY_ORDER]);
    expect(series[0]).toMatchObject({ label: "Crítica", count: 2, fill: "var(--sev-critical)" });
    expect(series[4]).toMatchObject({ label: "Informativa", count: 3, fill: "var(--sev-info)" });
  });
});

describe("totalOpen / criticalOpen", () => {
  it("adds every severity and exposes the critical count", () => {
    const counts = { critical: 2, high: 3, medium: 3, low: 1, info: 2 };
    expect(totalOpen(counts)).toBe(11);
    expect(criticalOpen(counts)).toBe(2);
  });

  it("is zero for an empty tenant", () => {
    expect(totalOpen({ critical: 0, high: 0, medium: 0, low: 0, info: 0 })).toBe(0);
  });
});

describe("trendSeries", () => {
  it("labels each day as dd/mm and keeps the counts", () => {
    const series = trendSeries([{ day: "2026-09-04", opened: 3, closed: 1 }]);
    expect(series).toEqual([{ day: "2026-09-04", label: "04/09", opened: 3, closed: 1 }]);
  });

  it("returns the raw day when it is not an ISO date", () => {
    expect(trendLabel("ayer")).toBe("ayer");
    expect(trendLabel("2026-09")).toBe("2026-09");
  });

  it("keeps all 30 days, even the empty ones", () => {
    expect(trendSeries(makeTrend())).toHaveLength(30);
  });
});

describe("trendTotals", () => {
  it("sums opened and closed", () => {
    expect(trendTotals(trendSeries(makeTrend()))).toEqual({ opened: 12, closed: 4 });
  });

  it("is zero for an empty series", () => {
    expect(trendTotals([])).toEqual({ opened: 0, closed: 0 });
  });
});

describe("hasAnyData", () => {
  it("is true with assets, findings, scans or trend", () => {
    expect(hasAnyData(makeDashboardSummary())).toBe(true);
  });

  it("is false for a freshly created organisation", () => {
    const empty = makeDashboardSummary({
      assets_monitored: 0,
      open_by_severity: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
      coverage_24h: { covered: 0, total: 0, ratio: null, since: "2026-10-09T15:00:00Z" },
      scan_success_30d: { completed: 0, failed: 0, ratio: null, since: "2026-09-10T15:00:00Z" },
      trend_30d: makeTrend().map((day) => ({ ...day, opened: 0, closed: 0 })),
    });

    expect(hasAnyData(empty)).toBe(false);
  });
});
