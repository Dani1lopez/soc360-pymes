import { lazy, Suspense } from "react";
import { Activity, CheckCircle2, RefreshCw, Server, ShieldAlert } from "lucide-react";
import { AsyncSection } from "@/components/async-section";
import { MetricCard } from "@/components/metric-card";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/features/auth";
import { formatDateTime, formatRatio } from "@/lib/format";
import {
  criticalOpen,
  hasAnyData,
  severitySeries,
  totalOpen,
  trendSeries,
  trendTotals,
} from "../lib/dashboard-metrics";
import { useDashboardSummary } from "../hooks/use-dashboard";

// Recharts pesa más que el resto de la página: entra en su propio trozo, solo
// cuando alguien abre el panel.
const TrendChart = lazy(() =>
  import("./trend-chart").then((module) => ({ default: module.TrendChart })),
);
const SeverityChart = lazy(() =>
  import("./severity-chart").then((module) => ({ default: module.SeverityChart })),
);

export function DashboardPage() {
  const { data: user } = useCurrentUser();
  const query = useDashboardSummary();
  const summary = query.data;

  return (
    <section className="space-y-6">
      <PageHeader
        title={user === undefined ? "Panel" : `Hola, ${user.full_name.split(" ")[0]}`}
        description="Resumen de la exposición de tu organización."
        actions={
          <Button
            variant="outline"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            <RefreshCw aria-hidden="true" className="size-4" />
            {query.isFetching ? "Actualizando…" : "Actualizar"}
          </Button>
        }
      />

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        onRetry={() => void query.refetch()}
      >
        {summary !== undefined && (
          <div className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <MetricCard
                label="Activos vigilados"
                value={summary.assets_monitored}
                hint={`${summary.coverage_24h.covered} escaneados en las últimas 24 h`}
                icon={<Server aria-hidden="true" className="size-4" />}
              />
              <MetricCard
                label="Hallazgos abiertos"
                value={totalOpen(summary.open_by_severity)}
                hint={`${criticalOpen(summary.open_by_severity)} críticos`}
                icon={<ShieldAlert aria-hidden="true" className="size-4" />}
              />
              <MetricCard
                label="Cobertura 24 h"
                value={formatRatio(summary.coverage_24h.ratio)}
                hint={`${summary.coverage_24h.covered} de ${summary.coverage_24h.total} activos`}
                icon={<Activity aria-hidden="true" className="size-4" />}
              />
              <MetricCard
                label="Éxito de escaneos 30 d"
                value={formatRatio(summary.scan_success_30d.ratio)}
                hint={`${summary.scan_success_30d.completed} correctos · ${summary.scan_success_30d.failed} fallidos`}
                icon={<CheckCircle2 aria-hidden="true" className="size-4" />}
              />
            </div>

            {!hasAnyData(summary) && (
              <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
                Todavía no hay datos: añade un activo, lanza un escaneo y vuelve a mirar aquí.
              </p>
            )}

            <Suspense
              fallback={
                <p role="status" className="text-sm text-muted-foreground">
                  Cargando gráficos…
                </p>
              }
            >
              <div className="grid gap-6 xl:grid-cols-2">
                <TrendChart
                  data={trendSeries(summary.trend_30d)}
                  totals={trendTotals(trendSeries(summary.trend_30d))}
                />
                <SeverityChart
                  data={severitySeries(summary.open_by_severity)}
                  total={totalOpen(summary.open_by_severity)}
                />
              </div>
            </Suspense>

            <p className="text-xs text-muted-foreground">
              Datos generados el {formatDateTime(summary.generated_at)}.
            </p>
          </div>
        )}
      </AsyncSection>
    </section>
  );
}
