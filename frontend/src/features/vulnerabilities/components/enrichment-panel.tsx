import { RefreshCw, Sparkles } from "lucide-react";
import { AsyncSection } from "@/components/async-section";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { enrichmentStatusLabel, enrichmentStatusTone } from "../lib/vulnerability-labels";
import {
  useRelaunchScanEnrichment,
  useRelaunchVulnerabilityEnrichment,
  useVulnerabilityEnrichment,
} from "../hooks/use-enrichment";

type EnrichmentPanelProps = {
  vulnerabilityId: string;
  scanId: string;
  /** admin, analyst o superadmin: el viewer solo lee. */
  canRelaunch: boolean;
};

/** Un ítem por función del nivel de enriquecimiento del tenant. */
export function EnrichmentPanel({ vulnerabilityId, scanId, canRelaunch }: EnrichmentPanelProps) {
  const query = useVulnerabilityEnrichment(vulnerabilityId);
  const relaunchOne = useRelaunchVulnerabilityEnrichment(vulnerabilityId);
  const relaunchScan = useRelaunchScanEnrichment(scanId);
  const items = query.data?.items ?? [];
  const error = relaunchOne.error ?? relaunchScan.error;

  return (
    <section
      aria-labelledby="enrichment-heading"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="enrichment-heading" className="flex items-center gap-2 text-lg font-semibold">
            <Sparkles aria-hidden="true" className="size-5 text-primary" />
            Análisis enriquecido
          </h2>
          {query.data !== undefined && (
            <p className="mt-1 text-sm text-muted-foreground">
              Nivel de la organización: {query.data.level}
            </p>
          )}
        </div>
        {canRelaunch && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={relaunchOne.isPending}
              onClick={() => relaunchOne.mutate()}
            >
              <RefreshCw aria-hidden="true" className="size-4" />
              Reintentar este hallazgo
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={relaunchScan.isPending}
              onClick={() => relaunchScan.mutate()}
            >
              <RefreshCw aria-hidden="true" className="size-4" />
              Relanzar el escaneo
            </Button>
          </div>
        )}
      </div>

      {relaunchOne.data !== undefined && (
        <p role="status" className="text-sm text-muted-foreground">
          {relaunchOne.data.queued > 0
            ? `En cola ${relaunchOne.data.queued} función(es) de este hallazgo.`
            : "No había nada que encolar: el análisis ya está al día."}
        </p>
      )}
      {relaunchScan.data !== undefined && (
        <p role="status" className="text-sm text-muted-foreground">
          {`En cola ${relaunchScan.data.queued} de ${relaunchScan.data.total} hallazgos del escaneo.`}
        </p>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(error)}
        </p>
      )}

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        isEmpty={items.length === 0}
        emptyTitle="Sin funciones de enriquecimiento"
        emptyMessage="Esta organización no tiene funciones activas para este nivel."
        onRetry={() => void query.refetch()}
      >
        <ul className="space-y-4">
          {items.map((item) => (
            <li key={item.function} className="rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{item.function}</span>
                <span
                  className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${enrichmentStatusTone(item.status)}`}
                >
                  {enrichmentStatusLabel(item.status)}
                </span>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">
                {item.model ?? "Sin modelo"}
                {item.prompt_version !== null ? ` · prompt ${item.prompt_version}` : ""}
                {` · intentos ${item.attempts}`}
                {item.updated_at !== null ? ` · ${formatDateTime(item.updated_at)}` : ""}
              </p>
              {item.content !== null && (
                <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap text-sm">
                  {item.content}
                </pre>
              )}
              {item.error !== null && <p className="mt-3 text-sm text-destructive">{item.error}</p>}
            </li>
          ))}
        </ul>
      </AsyncSection>
    </section>
  );
}
