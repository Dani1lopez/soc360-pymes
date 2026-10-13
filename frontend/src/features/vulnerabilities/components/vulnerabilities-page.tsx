import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import type { Severity } from "@/api/schema";
import { AsyncSection } from "@/components/async-section";
import { ConfirmButton } from "@/components/confirm-button";
import { PageHeader } from "@/components/page-header";
import { Pagination } from "@/components/pagination";
import { SEVERITY_LABELS, SeverityBadge } from "@/components/severity-badge";
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
import { scanAssetIds, useScanOptions } from "@/features/scans";
import { errorMessage } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import { VULNERABILITIES_PAGE_SIZE } from "../api/vulnerabilities-api";
import {
  NO_PAGE_FILTERS,
  type PageFilters,
  SEVERITIES,
  assetLabelForScan,
  filterPage,
  formatCvss,
} from "../lib/vulnerability-labels";
import { useVulnerabilities } from "../hooks/use-vulnerabilities";
import { useDeleteVulnerability } from "../hooks/use-vulnerability-mutations";
import { VulnerabilityForm } from "./vulnerability-form";
import { VulnerabilityStatusBadge } from "./vulnerability-status-badge";

export function VulnerabilitiesPage() {
  const [offset, setOffset] = useState(0);
  const [scanFilter, setScanFilter] = useState("");
  const [filters, setFilters] = useState<PageFilters>(NO_PAGE_FILTERS);
  const [creating, setCreating] = useState(false);
  const { data: user } = useCurrentUser();
  const scans = useScanOptions();
  const assets = useAssetOptions();
  const query = useVulnerabilities(offset, scanFilter === "" ? null : scanFilter);
  const remove = useDeleteVulnerability();

  // El backend decide con las mismas allowlists; aquí solo se oculta lo que
  // devolvería 403. `ENRICH_ROLES` gobierna el relanzado, en el detalle.
  const canWrite = hasAnyRole(user, ADMIN_ROLES);
  const tenantId = user?.tenant_id ?? null;
  const canCreate = canWrite && tenantId !== null;

  const scanAssets = scanAssetIds(scans.data?.items);
  const assetValues = assetValuesById(assets.data?.items);
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const visible = filterPage(items, filters);

  function handleDelete(id: string) {
    remove.mutate(id, {
      onSuccess: () => {
        if (visible.length === 1 && offset > 0) {
          setOffset(Math.max(0, offset - VULNERABILITIES_PAGE_SIZE));
        }
      },
    });
  }

  return (
    <section className="space-y-6">
      <PageHeader
        title="Vulnerabilidades"
        description="Hallazgos abiertos y cerrados de tus activos."
        actions={
          canCreate && (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden="true" className="size-4" />
              Registrar hallazgo
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <label htmlFor="vulnerability-filter-scan" className="text-sm font-medium">
            Filtrar por escaneo
          </label>
          <Select
            id="vulnerability-filter-scan"
            className="w-64"
            value={scanFilter}
            onChange={(event) => {
              setScanFilter(event.target.value);
              setOffset(0);
            }}
          >
            <option value="">Todos los escaneos</option>
            {(scans.data?.items ?? []).map((scan) => (
              <option key={scan.id} value={scan.id}>
                {scan.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <label htmlFor="vulnerability-filter-subset" className="text-sm font-medium">
            Mostrar
          </label>
          <Select
            id="vulnerability-filter-subset"
            value={filters.subset}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                subset: event.target.value as PageFilters["subset"],
              }))
            }
          >
            <option value="all">Todo</option>
            <option value="open">Solo abiertas</option>
          </Select>
        </div>
        <div className="space-y-2">
          <label htmlFor="vulnerability-filter-severity" className="text-sm font-medium">
            Filtrar por severidad
          </label>
          <Select
            id="vulnerability-filter-severity"
            value={filters.severity}
            onChange={(event) =>
              setFilters((current) => ({
                ...current,
                severity: event.target.value as Severity | "all",
              }))
            }
          >
            <option value="all">Todas</option>
            {SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {SEVERITY_LABELS[severity]}
              </option>
            ))}
          </Select>
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        «Mostrar» y «Severidad» filtran la página cargada: la API solo filtra por escaneo.
      </p>

      {canWrite && !canCreate && (
        <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          Para registrar hallazgos necesitas una cuenta asociada a una organización.
        </p>
      )}

      {remove.error !== null && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(remove.error)}
        </p>
      )}

      {creating && (
        <VulnerabilityForm
          tenantId={tenantId}
          initialScanId={scanFilter}
          onCancel={() => setCreating(false)}
          onSaved={() => setCreating(false)}
        />
      )}

      <AsyncSection
        isPending={query.isPending}
        isFetching={query.isFetching}
        error={query.error}
        isEmpty={visible.length === 0}
        emptyTitle="No hay hallazgos"
        emptyMessage="Cuando un escaneo encuentre algo, aparecerá aquí."
        onRetry={() => void query.refetch()}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hallazgo</TableHead>
              <TableHead>Activo</TableHead>
              <TableHead>Severidad</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>CVSS</TableHead>
              <TableHead>CVE</TableHead>
              <TableHead>Creada</TableHead>
              {canWrite && <TableHead>Acciones</TableHead>}
            </TableRow>
          </TableHeader>
          <TableBody>
            {visible.map((vulnerability) => (
              <TableRow key={vulnerability.id}>
                <TableCell className="font-medium">
                  <Link
                    to="/vulnerabilities/$id"
                    params={{ id: vulnerability.id }}
                    className="text-primary hover:underline"
                  >
                    {vulnerability.title}
                  </Link>
                </TableCell>
                <TableCell className="break-all text-muted-foreground">
                  {assetLabelForScan(vulnerability.scan_id, scanAssets, assetValues)}
                </TableCell>
                <TableCell>
                  <SeverityBadge severity={vulnerability.severity} />
                </TableCell>
                <TableCell>
                  <VulnerabilityStatusBadge status={vulnerability.status} />
                </TableCell>
                <TableCell>{formatCvss(vulnerability.cvss_score)}</TableCell>
                <TableCell className="text-muted-foreground">
                  {vulnerability.cve_id ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(vulnerability.created_at)}
                </TableCell>
                {canWrite && (
                  <TableCell>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="outline" size="sm" asChild>
                        <Link to="/vulnerabilities/$id" params={{ id: vulnerability.id }}>
                          Ver detalle
                        </Link>
                      </Button>
                      <ConfirmButton
                        label="Eliminar"
                        confirmLabel="Eliminar hallazgo"
                        question="¿Eliminar el hallazgo?"
                        disabled={remove.isPending}
                        onConfirm={() => handleDelete(vulnerability.id)}
                      />
                    </div>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Pagination
          total={total}
          limit={VULNERABILITIES_PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
        />
      </AsyncSection>
    </section>
  );
}
