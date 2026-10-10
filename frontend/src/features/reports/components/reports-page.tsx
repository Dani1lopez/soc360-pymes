import { useState } from "react";
import { Plus } from "lucide-react";
import type { ReportResponse } from "@/api/schema";
import { AsyncSection } from "@/components/async-section";
import { ConfirmButton } from "@/components/confirm-button";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ADMIN_ROLES, hasAnyRole, useCurrentUser } from "@/features/auth";
import { assetValuesById, useAssetOptions } from "@/features/assets";
import { errorMessage } from "@/lib/errors";
import { formatDateTime, orDash } from "@/lib/format";
import { REPORTS_PAGE_SIZE } from "../api/reports-api";
import {
  REPORT_STATUSES,
  REPORT_TYPES,
  reportStatusLabel,
  reportTypeLabel,
} from "../lib/report-labels";
import { useReports } from "../hooks/use-reports";
import { useDeleteReport } from "../hooks/use-report-mutations";
import { ReportForm } from "./report-form";
import { ReportStatusBadge } from "./report-status-badge";

type Editor = { report: ReportResponse | null } | null;

export function ReportsPage() {
  const [offset, setOffset] = useState(0);
  const [assetFilter, setAssetFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [editor, setEditor] = useState<Editor>(null);
  const { data: user } = useCurrentUser();
  const assets = useAssetOptions();
  const query = useReports({
    offset,
    assetId: assetFilter === "" ? null : assetFilter,
    reportType: typeFilter === "" ? null : typeFilter,
    status: statusFilter === "" ? null : statusFilter,
  });
  const remove = useDeleteReport();

  const canWrite = hasAnyRole(user, ADMIN_ROLES);
  const tenantId = user?.tenant_id ?? null;
  const canCreate = canWrite && tenantId !== null;
  const assetNames = assetValuesById(assets.data?.items);
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  function closeEditor() {
    setEditor(null);
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Informes"
        description="Metadatos de los informes de tus activos."
        actions={
          canCreate && (
            <Button onClick={() => setEditor({ report: null })}>
              <Plus aria-hidden="true" className="size-4" />
              Nuevo informe
            </Button>
          )
        }
      />
      <p className="text-sm text-muted-foreground">
        La generación y la descarga de PDF llegan en una fase posterior: aquí se gestiona el
        registro del informe y su estado.
      </p>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor="report-filter-asset" className="text-sm font-medium">
            Activo
          </label>
          <Select
            id="report-filter-asset"
            className="w-56"
            value={assetFilter}
            onChange={(event) => {
              setAssetFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos los activos</option>
            {(assets.data?.items ?? []).map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.value}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <label htmlFor="report-filter-type" className="text-sm font-medium">
            Tipo
          </label>
          <Select
            id="report-filter-type"
            value={typeFilter}
            onChange={(event) => {
              setTypeFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos los tipos</option>
            {REPORT_TYPES.map((type) => (
              <option key={type} value={type}>
                {reportTypeLabel(type)}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <label htmlFor="report-filter-status" className="text-sm font-medium">
            Estado
          </label>
          <Select
            id="report-filter-status"
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos los estados</option>
            {REPORT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {reportStatusLabel(status)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      {canWrite && !canCreate && (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Para gestionar informes necesitas una cuenta asociada a una organización.
        </p>
      )}

      {remove.error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(remove.error)}
        </p>
      )}

      {editor !== null && (
        <ReportForm
          report={editor.report}
          tenantId={tenantId}
          initialAssetId={assetFilter}
          onCancel={closeEditor}
          onSaved={closeEditor}
        />
      )}

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        isEmpty={items.length === 0}
        emptyTitle="No hay informes"
        emptyMessage="Crea el registro de un informe para seguir su estado."
        onRetry={() => void query.refetch()}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Activo</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Generado</TableHead>
              <TableHead>Actualizado</TableHead>
              {canWrite && <TableHead>Acciones</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((report) => (
              <TableRow key={report.id}>
                <TableCell className="font-medium">{report.name}</TableCell>
                <TableCell className="break-all text-muted-foreground">
                  {orDash(assetNames[report.asset_id])}
                </TableCell>
                <TableCell>{reportTypeLabel(report.report_type)}</TableCell>
                <TableCell>
                  <ReportStatusBadge status={report.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(report.generated_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(report.updated_at)}
                </TableCell>
                {canWrite && (
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setEditor({ report })}>
                        Editar
                      </Button>
                      <ConfirmButton
                        label="Eliminar"
                        confirmLabel="Eliminar informe"
                        question="¿Eliminar el informe?"
                        disabled={remove.isPending}
                        onConfirm={() => remove.mutate(report.id)}
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Pagination total={total} limit={REPORTS_PAGE_SIZE} offset={offset} onChange={setOffset} />
      </AsyncSection>
    </section>
  );
}
