import type { DashboardSummary, Severity, SeverityCounts, TrendDay } from "@/api/schema";
import { SEVERITY_LABELS } from "@/components/severity-badge";

/** Orden de presentación: de más a menos grave, como en el backend. */
export const SEVERITY_ORDER = [
  "critical",
  "high",
  "medium",
  "low",
  "info",
] as const satisfies readonly Severity[];

/** Color de cada barra: el mismo token que usa la insignia de severidad. */
const SEVERITY_FILLS: Record<Severity, string> = {
  critical: "var(--sev-critical)",
  high: "var(--sev-high)",
  medium: "var(--sev-medium)",
  low: "var(--sev-low)",
  info: "var(--sev-info)",
};

export type SeverityDatum = {
  severity: Severity;
  label: string;
  count: number;
  fill: string;
};

/** Serie por severidad con la etiqueta y el color ya resueltos. */
export function severitySeries(counts: SeverityCounts): SeverityDatum[] {
  return SEVERITY_ORDER.map((severity) => ({
    severity,
    label: SEVERITY_LABELS[severity],
    count: counts[severity],
    fill: SEVERITY_FILLS[severity],
  }));
}

export function totalOpen(counts: SeverityCounts): number {
  return SEVERITY_ORDER.reduce((total, severity) => total + counts[severity], 0);
}

export function criticalOpen(counts: SeverityCounts): number {
  return counts.critical;
}

export type TrendDatum = { day: string; label: string; opened: number; closed: number };

/** dd/mm a partir del día ISO que devuelve la API. */
export function trendLabel(day: string): string {
  const [, month, dayOfMonth] = day.split("-");
  if (month === undefined || dayOfMonth === undefined) return day;
  return `${dayOfMonth}/${month}`;
}

/** Serie de 30 días lista para Recharts. */
export function trendSeries(trend: TrendDay[]): TrendDatum[] {
  return trend.map((point) => ({
    day: point.day,
    label: trendLabel(point.day),
    opened: point.opened,
    closed: point.closed,
  }));
}

export function trendTotals(series: TrendDatum[]): { opened: number; closed: number } {
  return series.reduce(
    (totals, point) => ({
      opened: totals.opened + point.opened,
      closed: totals.closed + point.closed,
    }),
    { opened: 0, closed: 0 },
  );
}

/** ¿Hay algo que enseñar? Una organización recién creada no tiene nada. */
export function hasAnyData(summary: DashboardSummary): boolean {
  return (
    summary.assets_monitored > 0 ||
    summary.coverage_24h.covered > 0 ||
    summary.scan_success_30d.completed > 0 ||
    totalOpen(summary.open_by_severity) > 0 ||
    summary.trend_30d.some((day) => day.opened > 0 || day.closed > 0)
  );
}
