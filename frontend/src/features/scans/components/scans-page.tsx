import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Plus, Play, Square } from "lucide-react";
import type { ScanResponse } from "@/api/schema";
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
import { SCANS_PAGE_SIZE } from "../api/scans-api";
import { canCancelScan, canRunScan, scanTypeLabel } from "../lib/scan-labels";
import { useScans } from "../hooks/use-scans";
import { useCancelScan, useDeleteScan, useRunScan } from "../hooks/use-scan-mutations";
import { ScanForm } from "./scan-form";
import { ScanStatusBadge } from "./scan-status-badge";

type Editor = { scan: ScanResponse | null } | null;

export function ScansPage() {
  const [offset, setOffset] = useState(0);
  const [assetFilter, setAssetFilter] = useState("");
  const [editor, setEditor] = useState<Editor>(null);
  const { data: user } = useCurrentUser();
  const assets = useAssetOptions();
  const query = useScans(offset, assetFilter === "" ? null : assetFilter);
  const remove = useDeleteScan();
  const run = useRunScan();
  const cancel = useCancelScan();

  const canWrite = hasAnyRole(user, ADMIN_ROLES);
  const tenantId = user?.tenant_id ?? null;
  const canCreate = canWrite && tenantId !== null;
  const assetNames = assetValuesById(assets.data?.items);

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const actionError = run.error ?? cancel.error ?? remove.error;

  function closeEditor() {
    setEditor(null);
  }

  function handleDelete(id: string) {
    remove.mutate(id, {
      onSuccess: () => {
        if (items.length === 1 && offset > 0) setOffset(Math.max(0, offset - SCANS_PAGE_SIZE));
      },
    });
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Escaneos"
        description="Qué se ha lanzado sobre tus activos y en qué estado está."
        actions={
          canCreate && (
            <Button onClick={() => setEditor({ scan: null })}>
              <Plus aria-hidden="true" className="size-4" />
              Nuevo escaneo
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor="scan-filter-asset" className="text-sm font-medium">
            Filtrar por activo
          </label>
          <Select
            id="scan-filter-asset"
            className="w-64"
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
      </div>

      {canWrite && !canCreate && (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Para crear escaneos necesitas una cuenta asociada a una organización.
        </p>
      )}

      {actionError !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(actionError)}
        </p>
      )}

      {editor !== null && (
        <ScanForm
          scan={editor.scan}
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
        emptyTitle="No hay escaneos"
        emptyMessage="Crea un escaneo sobre un activo para empezar a medir su exposición."
        onRetry={() => void query.refetch()}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nombre</TableHead>
              <TableHead>Activo</TableHead>
              <TableHead>Tipo</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Creado</TableHead>
              {canWrite && <TableHead>Acciones</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((scan) => (
              <TableRow key={scan.id}>
                <TableCell className="font-medium">
                  <Link
                    to="/scans/$id"
                    params={{ id: scan.id }}
                    className="text-primary hover:underline"
                  >
                    {scan.name}
                  </Link>
                </TableCell>
                <TableCell className="break-all text-muted-foreground">
                  {orDash(assetNames[scan.asset_id])}
                </TableCell>
                <TableCell>{scanTypeLabel(scan.type)}</TableCell>
                <TableCell>
                  <ScanStatusBadge status={scan.status} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(scan.created_at)}
                </TableCell>
                {canWrite && (
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      {canRunScan(scan) && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={run.isPending}
                          onClick={() => run.mutate(scan.id)}
                        >
                          <Play aria-hidden="true" className="size-4" />
                          Ejecutar
                        </Button>
                      )}
                      {canCancelScan(scan) && (
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={cancel.isPending}
                          onClick={() => cancel.mutate(scan.id)}
                        >
                          <Square aria-hidden="true" className="size-4" />
                          Cancelar
                        </Button>
                      )}
                      <Button variant="outline" size="sm" onClick={() => setEditor({ scan })}>
                        Editar
                      </Button>
                      <ConfirmButton
                        label="Eliminar"
                        confirmLabel="Eliminar escaneo"
                        question="¿Eliminar el escaneo?"
                        disabled={remove.isPending}
                        onConfirm={() => handleDelete(scan.id)}
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Pagination total={total} limit={SCANS_PAGE_SIZE} offset={offset} onChange={setOffset} />
      </AsyncSection>
    </section>
  );
}
