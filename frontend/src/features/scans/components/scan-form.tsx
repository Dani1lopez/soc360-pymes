import { useState, type FormEvent } from "react";
import type { ScanResponse, ScanType } from "@/api/schema";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useAssetOptions } from "@/features/assets";
import { errorMessage, fieldError } from "@/lib/errors";
import { SCAN_TYPES, scanTypeLabel } from "../lib/scan-labels";
import {
  type ScanFormErrors,
  type ScanFormState,
  emptyScanForm,
  formFromScan,
  hasScanFormErrors,
  needsChecks,
  needsHostDiscovery,
  needsPaths,
  toScanCreateInput,
  toScanUpdateInput,
  validateScanForm,
} from "../lib/scan-form";
import { useCreateScan, useUpdateScan } from "../hooks/use-scan-mutations";

type ScanFormProps = {
  /** null al crear; el escaneo editado en caso contrario. */
  scan: ScanResponse | null;
  /** Activo preseleccionado al crear desde un activo concreto. */
  initialAssetId?: string;
  tenantId: string | null;
  onSaved: () => void;
  onCancel: () => void;
};

export function ScanForm({ scan, initialAssetId, tenantId, onSaved, onCancel }: ScanFormProps) {
  const isEdit = scan !== null;
  const [state, setState] = useState<ScanFormState>(() =>
    scan === null ? emptyScanForm(initialAssetId) : formFromScan(scan),
  );
  const [errors, setErrors] = useState<ScanFormErrors>({});
  const assets = useAssetOptions();
  const create = useCreateScan();
  const update = useUpdateScan();
  const mutation = isEdit ? update : create;

  function updateField<K extends keyof ScanFormState>(field: K, value: ScanFormState[K]) {
    setState((current) => ({ ...current, [field]: value }));
  }

  const serverError = mutation.error !== null ? errorMessage(mutation.error) : null;
  const nameError = errors.name ?? fieldError(mutation.error, "name");
  const assetError = errors.assetId;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const validation = validateScanForm(state);
    setErrors(validation);
    if (hasScanFormErrors(validation)) return;
    if (scan === null) {
      if (tenantId === null) return;
      create.mutate(toScanCreateInput(state, tenantId), { onSuccess: onSaved });
    } else {
      update.mutate({ id: scan.id, input: toScanUpdateInput(state) }, { onSuccess: onSaved });
    }
  }

  return (
    <section
      aria-labelledby="scan-form-heading"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="scan-form-heading" className="text-lg font-semibold">
        {isEdit ? "Editar escaneo" : "Nuevo escaneo"}
      </h2>
      {/* noValidate: los mensajes en español los pone la validación propia. */}
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <FormField id="scan-name" label="Nombre" error={nameError}>
          <Input
            id="scan-name"
            required
            maxLength={255}
            value={state.name}
            onChange={(event) => updateField("name", event.target.value)}
            aria-invalid={nameError !== undefined ? true : undefined}
            aria-describedby={nameError !== undefined ? "scan-name-error" : undefined}
          />
        </FormField>

        <FormField id="scan-asset" label="Activo" error={assetError}>
          <Select
            id="scan-asset"
            required
            disabled={isEdit}
            value={state.assetId}
            onChange={(event) => updateField("assetId", event.target.value)}
            aria-invalid={assetError !== undefined ? true : undefined}
            aria-describedby={assetError !== undefined ? "scan-asset-error" : undefined}
          >
            <option value="">Selecciona un activo…</option>
            {(assets.data?.items ?? []).map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.value}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField
          id="scan-type"
          label="Tipo"
          hint="Cambiar el tipo cambia las opciones de configuración."
        >
          <Select
            id="scan-type"
            value={state.type}
            onChange={(event) => updateField("type", event.target.value as ScanType)}
          >
            {SCAN_TYPES.map((type) => (
              <option key={type} value={type}>
                {scanTypeLabel(type)}
              </option>
            ))}
          </Select>
        </FormField>

        {needsHostDiscovery(state.type) && (
          <div className="flex items-center gap-2">
            <input
              id="scan-host-discovery"
              type="checkbox"
              checked={state.hostDiscovery}
              onChange={(event) => updateField("hostDiscovery", event.target.checked)}
              className="size-4 rounded border-input"
            />
            <label htmlFor="scan-host-discovery" className="text-sm font-medium">
              Incluir descubrimiento de hosts
            </label>
          </div>
        )}

        {needsChecks(state.type) && (
          <FormField
            id="scan-checks"
            label="Comprobaciones"
            hint="Separadas por comas, por ejemplo: tls, headers"
            error={errors.checks}
          >
            <Input
              id="scan-checks"
              value={state.checks}
              onChange={(event) => updateField("checks", event.target.value)}
              aria-invalid={errors.checks !== undefined ? true : undefined}
              aria-describedby={errors.checks !== undefined ? "scan-checks-error" : undefined}
            />
          </FormField>
        )}

        {needsPaths(state.type) && (
          <FormField
            id="scan-paths"
            label="Rutas"
            hint="Separadas por comas, por ejemplo: /, /login"
            error={errors.paths}
          >
            <Input
              id="scan-paths"
              value={state.paths}
              onChange={(event) => updateField("paths", event.target.value)}
              aria-invalid={errors.paths !== undefined ? true : undefined}
              aria-describedby={errors.paths !== undefined ? "scan-paths-error" : undefined}
            />
          </FormField>
        )}

        {serverError !== null && (
          <p role="alert" className="text-sm text-destructive">
            {serverError}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear escaneo"}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
        </div>
      </form>
    </section>
  );
}
