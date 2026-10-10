import { useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, Play, Square } from "lucide-react";
import { AsyncSection } from "@/components/async-section";
import { ConfirmButton } from "@/components/confirm-button";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { ADMIN_ROLES, hasAnyRole, useCurrentUser } from "@/features/auth";
import { assetValuesById, useAssetOptions } from "@/features/assets";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, orDash } from "@/lib/format";
import { canCancelScan, canRunScan, scanConfigSummary, scanTypeLabel } from "../lib/scan-labels";
import { useScan } from "../hooks/use-scans";
import { useCancelScan, useDeleteScan, useRunScan } from "../hooks/use-scan-mutations";
import { ScanForm } from "./scan-form";
import { ScanStatusBadge } from "./scan-status-badge";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</dt>
      <dd className="mt-1 text-sm">{value}</dd>
    </div>
  );
}

export function ScanDetailPage({ scanId }: { scanId: string }) {
  const navigate = useNavigate();
  const { data: user } = useCurrentUser();
  const assets = useAssetOptions();
  const query = useScan(scanId);
  const remove = useDeleteScan();
  const run = useRunScan();
  const cancel = useCancelScan();
  const [editing, setEditing] = useState(false);

  const canWrite = hasAnyRole(user, ADMIN_ROLES);
  const tenantId = user?.tenant_id ?? null;
  const scan = query.data;
  const assetNames = assetValuesById(assets.data?.items);
  const actionError = run.error ?? cancel.error ?? remove.error;

  return (
    <section className="space-y-6">
      <Link
        to="/scans"
        className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4" />
        Volver a escaneos
      </Link>

      <AsyncSection
        isPending={query.isPending}
        error={query.error}
        onRetry={() => void query.refetch()}
      >
        {scan !== undefined && (
          <div className="space-y-6">
            <PageHeader
              title={scan.name}
              description={`Creado el ${formatDateTime(scan.created_at)}`}
              actions={
                <>
                  <ScanStatusBadge status={scan.status} />
                  {canWrite && canRunScan(scan) && (
                    <Button disabled={run.isPending} onClick={() => run.mutate(scan.id)}>
                      <Play aria-hidden="true" className="size-4" />
                      Ejecutar
                    </Button>
                  )}
                  {canWrite && canCancelScan(scan) && (
                    <Button
                      variant="outline"
                      disabled={cancel.isPending}
                      onClick={() => cancel.mutate(scan.id)}
                    >
                      <Square aria-hidden="true" className="size-4" />
                      Cancelar
                    </Button>
                  )}
                  {canWrite && (
                    <>
                      <Button variant="outline" onClick={() => setEditing(true)}>
                        Editar
                      </Button>
                      <ConfirmButton
                        label="Eliminar"
                        confirmLabel="Eliminar escaneo"
                        question="¿Eliminar el escaneo y sus hallazgos?"
                        disabled={remove.isPending}
                        onConfirm={() =>
                          remove.mutate(scan.id, {
                            onSuccess: () => void navigate({ to: "/scans" }),
                          })
                        }
                      />
                    </>
                  )}
                </>
              }
            />

            {actionError !== null && (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage(actionError)}
              </p>
            )}

            {editing && (
              <ScanForm
                scan={scan}
                tenantId={tenantId}
                onCancel={() => setEditing(false)}
                onSaved={() => setEditing(false)}
              />
            )}

            <dl className="grid gap-4 rounded-lg border border-border bg-card p-6 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Activo" value={orDash(assetNames[scan.asset_id])} />
              <Field label="Tipo" value={scanTypeLabel(scan.type)} />
              <Field label="Configuración" value={scanConfigSummary(scan.config)} />
              <Field label="Iniciado" value={formatDateTime(scan.started_at)} />
              <Field label="Terminado" value={formatDateTime(scan.completed_at)} />
              <Field label="Actualizado" value={formatDateTime(scan.updated_at)} />
            </dl>
          </div>
        )}
      </AsyncSection>
    </section>
  );
}
