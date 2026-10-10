import { useState } from "react";
import { Download, Plus } from "lucide-react";
import type { AssetResponse } from "@/api/schema";
import { AsyncSection } from "@/components/async-section";
import { ConfirmButton } from "@/components/confirm-button";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ADMIN_ROLES, hasAnyRole, useCurrentUser } from "@/features/auth";
import { downloadTextFile } from "@/lib/download";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { ASSETS_PAGE_SIZE } from "../api/assets-api";
import { assetTypeLabel } from "../lib/asset-types";
import { useAssets } from "../hooks/use-assets";
import { useDeleteAsset, useExportAssets } from "../hooks/use-asset-mutations";
import { AssetForm } from "./asset-form";

type Editor = { asset: AssetResponse | null } | null;

export function AssetsPage() {
  const [offset, setOffset] = useState(0);
  const [editor, setEditor] = useState<Editor>(null);
  const { data: user } = useCurrentUser();
  const query = useAssets(offset);
  const remove = useDeleteAsset();
  const exportCsv = useExportAssets();

  // El backend decide con las mismas allowlists; aquí solo se oculta lo que el
  // usuario no puede hacer para no ofrecer acciones que devolverían 403.
  const canWrite = hasAnyRole(user, ADMIN_ROLES);
  const tenantId = user?.tenant_id ?? null;
  const canCreate = canWrite && tenantId !== null;

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  function closeEditor() {
    setEditor(null);
  }

  function handleDelete(id: string) {
    remove.mutate(id, {
      // Última fila de una página que no es la primera: retroceder evita
      // quedarse mirando una página vacía.
      onSuccess: () => {
        if (items.length === 1 && offset > 0) setOffset(Math.max(0, offset - ASSETS_PAGE_SIZE));
      },
    });
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Activos"
        description="Inventario de la superficie expuesta de tu organización."
        actions={
          <>
            <Button
              variant="outline"
              disabled={exportCsv.isPending}
              onClick={() =>
                exportCsv.mutate(undefined, {
                  onSuccess: (csv) => downloadTextFile(csv, "activos.csv"),
                })
              }
            >
              <Download aria-hidden="true" className="size-4" />
              {exportCsv.isPending ? "Exportando…" : "Exportar CSV"}
            </Button>
            {canCreate && (
              <Button onClick={() => setEditor({ asset: null })}>
                <Plus aria-hidden="true" className="size-4" />
                Nuevo activo
              </Button>
            )}
          </>
        }
      />

      {canWrite && !canCreate && (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Para crear activos necesitas una cuenta asociada a una organización.
        </p>
      )}
      {exportCsv.error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(exportCsv.error, "No se pudo exportar el CSV.")}
        </p>
      )}

      {editor !== null && (
        <AssetForm
          asset={editor.asset}
          tenantId={tenantId}
          onCancel={closeEditor}
          onSaved={closeEditor}
        />
      )}

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        isEmpty={items.length === 0}
        emptyTitle="No hay activos"
        emptyMessage="Añade un dominio, una IP o una subred para empezar a vigilarla."
        onRetry={() => void query.refetch()}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tipo</TableHead>
              <TableHead>Valor</TableHead>
              <TableHead>Alta</TableHead>
              <TableHead>Actualizado</TableHead>
              {canWrite && <TableHead>Acciones</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((asset) => (
              <TableRow key={asset.id}>
                <TableCell>{assetTypeLabel(asset.type)}</TableCell>
                <TableCell className="font-medium break-all">{asset.value}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(asset.created_at)}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(asset.updated_at)}
                </TableCell>
                {canWrite && (
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="outline" size="sm" onClick={() => setEditor({ asset })}>
                        Editar
                      </Button>
                      <ConfirmButton
                        label="Eliminar"
                        confirmLabel="Dar de baja"
                        question="¿Dar de baja el activo?"
                        disabled={remove.isPending}
                        onConfirm={() => handleDelete(asset.id)}
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Pagination total={total} limit={ASSETS_PAGE_SIZE} offset={offset} onChange={setOffset} />
      </AsyncSection>
    </section>
  );
}
