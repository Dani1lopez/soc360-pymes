import { useState, type FormEvent } from "react";
import type { ReportResponse, ReportStatus, ReportType } from "@/api/schema";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAssetOptions } from "@/features/assets";
import { errorMessage, fieldError } from "@/lib/errors";
import {
  REPORT_STATUSES,
  REPORT_TYPES,
  reportStatusLabel,
  reportTypeLabel,
} from "../lib/report-labels";
import {
  type ReportFormErrors,
  type ReportFormState,
  emptyReportForm,
  formFromReport,
  hasReportFormErrors,
  toReportCreateInput,
  toReportUpdateInput,
  validateReportForm,
} from "../lib/report-form";
import { useCreateReport, useUpdateReport } from "../hooks/use-report-mutations";

type ReportFormProps = {
  /** null al crear; el informe editado en caso contrario. */
  report: ReportResponse | null;
  /** Activo preseleccionado al crear desde un filtro. */
  initialAssetId?: string;
  tenantId: string | null;
  onSaved: () => void;
  onCancel: () => void;
};

/**
 * Alta y edición de metadatos. Al editar, el activo y el tipo no se tocan:
 * identifican el informe y el backend no los acepta en PATCH.
 */
export function ReportForm({
  report,
  initialAssetId,
  tenantId,
  onSaved,
  onCancel,
}: ReportFormProps) {
  const isEdit = report !== null;
  const [state, setState] = useState<ReportFormState>(() =>
    report === null ? emptyReportForm(initialAssetId) : formFromReport(report),
  );
  const [errors, setErrors] = useState<ReportFormErrors>({});
  const assets = useAssetOptions();
  const create = useCreateReport();
  const update = useUpdateReport();
  const mutation = isEdit ? update : create;

  function updateField<K extends keyof ReportFormState>(field: K, value: ReportFormState[K]) {
    setState((current) => ({ ...current, [field]: value }));
  }

  const serverError = mutation.error !== null ? errorMessage(mutation.error) : null;
  const nameError = errors.name ?? fieldError(mutation.error, "name");
  const assetError = errors.assetId;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const validation = validateReportForm(state);
    setErrors(validation);
    if (hasReportFormErrors(validation)) return;
    if (report === null) {
      if (tenantId === null) return;
      create.mutate(toReportCreateInput(state, tenantId), { onSuccess: onSaved });
    } else {
      update.mutate({ id: report.id, input: toReportUpdateInput(state) }, { onSuccess: onSaved });
    }
  }

  return (
    <section
      aria-labelledby="report-form-heading"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="report-form-heading" className="text-lg font-semibold">
        {isEdit ? "Editar informe" : "Nuevo informe"}
      </h2>
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <FormField id="report-name" label="Nombre" error={nameError}>
          <Input
            id="report-name"
            maxLength={255}
            value={state.name}
            onChange={(event) => updateField("name", event.target.value)}
            aria-invalid={nameError !== undefined ? true : undefined}
            aria-describedby={nameError !== undefined ? "report-name-error" : undefined}
          />
        </FormField>

        {!isEdit && (
          <>
            <FormField id="report-asset" label="Activo" error={assetError}>
              <Select
                id="report-asset"
                value={state.assetId}
                onChange={(event) => updateField("assetId", event.target.value)}
                aria-invalid={assetError !== undefined ? true : undefined}
                aria-describedby={assetError !== undefined ? "report-asset-error" : undefined}
              >
                <option value="">Selecciona un activo…</option>
                {(assets.data?.items ?? []).map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.value}
                  </option>
                ))}
              </Select>
            </FormField>

            <FormField id="report-type" label="Tipo">
              <Select
                id="report-type"
                value={state.reportType}
                onChange={(event) => updateField("reportType", event.target.value as ReportType)}
              >
                {REPORT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {reportTypeLabel(type)}
                  </option>
                ))}
              </Select>
            </FormField>
          </>
        )}

        {isEdit && (
          <FormField id="report-status" label="Estado">
            <Select
              id="report-status"
              value={state.status}
              onChange={(event) => updateField("status", event.target.value as ReportStatus)}
            >
              {REPORT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {reportStatusLabel(status)}
                </option>
              ))}
            </Select>
          </FormField>
        )}

        <FormField
          id="report-summary"
          label="Resumen"
          hint="Opcional: lo que un humano debe saber del informe."
        >
          <Textarea
            id="report-summary"
            value={state.summary}
            onChange={(event) => updateField("summary", event.target.value)}
          />
        </FormField>

        {serverError !== null && (
          <p role="alert" className="text-sm text-destructive">
            {serverError}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear informe"}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
        </div>
      </form>
    </section>
  );
}
