import type { ReactNode } from "react";

type MetricCardProps = {
  label: string;
  value: string | number;
  hint?: string;
  icon?: ReactNode;
};

export function MetricCard({ label, value, hint, icon }: MetricCardProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-6 text-card-foreground shadow-sm">
      <dl>
        <dt className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
          {label}
          {icon && <span aria-hidden="true">{icon}</span>}
        </dt>
        <dd className="my-3 text-3xl font-semibold tracking-tight">{value}</dd>
      </dl>
      {hint !== undefined && <p className="text-sm text-muted-foreground">{hint}</p>}
    </div>
  );
}
