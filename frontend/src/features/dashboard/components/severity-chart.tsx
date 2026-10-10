import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SeverityDatum } from "../lib/dashboard-metrics";

type SeverityChartProps = {
  data: SeverityDatum[];
  total: number;
};

/** Hallazgos abiertos por severidad. El color no es el único canal: hay etiquetas. */
export function SeverityChart({ data, total }: SeverityChartProps) {
  return (
    <figure className="space-y-2 rounded-lg border border-border bg-card p-6">
      <figcaption className="text-sm font-medium">Hallazgos abiertos por severidad</figcaption>
      <div
        role="img"
        aria-label={`Hallazgos abiertos por severidad: ${data
          .map((datum) => `${datum.label} ${datum.count}`)
          .join(", ")}. Total: ${total}.`}
        className="h-64"
      >
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis
              dataKey="label"
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
              cursor={{ fill: "var(--accent)" }}
              contentStyle={{
                backgroundColor: "var(--card)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                color: "var(--card-foreground)",
              }}
            />
            <Bar dataKey="count" name="Abiertos">
              {data.map((datum) => (
                <Cell key={datum.severity} fill={datum.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {data.map((datum) => (
          <li key={datum.severity}>
            {datum.label}: {datum.count}
          </li>
        ))}
      </ul>
    </figure>
  );
}
