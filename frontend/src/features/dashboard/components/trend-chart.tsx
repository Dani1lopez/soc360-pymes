import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { TrendDatum } from "../lib/dashboard-metrics";

type TrendChartProps = {
  data: TrendDatum[];
  totals: { opened: number; closed: number };
};

/** Abiertos y cerrados en 30 días. El resumen textual hace el gráfico legible. */
export function TrendChart({ data, totals }: TrendChartProps) {
  return (
    <figure className="space-y-2 rounded-lg border border-border bg-card p-6">
      <figcaption className="text-sm font-medium">
        Hallazgos abiertos y cerrados (30 días)
      </figcaption>
      <div
        role="img"
        aria-label={`Tendencia de los últimos 30 días: ${totals.opened} hallazgos abiertos y ${totals.closed} cerrados.`}
        className="h-64"
      >
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="label"
              interval={4}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              stroke="var(--border)"
            />
            <YAxis
              allowDecimals={false}
              width={32}
              tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
              stroke="var(--border)"
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--card-foreground)",
              }}
            />
            <Area
              type="monotone"
              dataKey="opened"
              name="Abiertos"
              stroke="var(--sev-critical)"
              fill="var(--sev-critical)"
              fillOpacity={0.25}
            />
            <Area
              type="monotone"
              dataKey="closed"
              name="Cerrados"
              stroke="var(--sev-ok)"
              fill="var(--sev-ok)"
              fillOpacity={0.25}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Abiertos: {totals.opened} · Cerrados: {totals.closed}
      </p>
    </figure>
  );
}
