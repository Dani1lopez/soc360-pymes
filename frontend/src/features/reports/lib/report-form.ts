import type {
  ReportCreateInput,
  ReportResponse,
  ReportStatus,
  ReportType,
  ReportUpdateInput,
} from "@/api/schema";

/** Estado del formulario de alta y edición, en texto. */
export type ReportFormState = {
  name: string;
  assetId: string;
  reportType: ReportType;
  status: ReportStatus;
  summary: string;
};

export type ReportFormErrors = Partial<Record<"name" | "assetId" | "summary", string>>;

export function emptyReportForm(assetId = ""): ReportFormState {
  return { name: "", assetId, reportType: "vulnerability", status: "pending", summary: "" };
}

export function formFromReport(report: ReportResponse): ReportFormState {
  return {
    name: report.name,
    assetId: report.asset_id,
    reportType: report.report_type,
    status: report.status,
    summary: report.summary ?? "",
  };
}

/** Validación alineada con `app/modules/reports/schemas.py`. */
export function validateReportForm(state: ReportFormState): ReportFormErrors {
  const errors: ReportFormErrors = {};
  const name = state.name.trim();
  if (name === "") errors.name = "Introduce un nombre.";
  else if (name.length > 255) errors.name = "El nombre no puede superar 255 caracteres.";
  if (state.assetId === "") errors.assetId = "Selecciona el activo del informe.";
  return errors;
}

export function hasReportFormErrors(errors: ReportFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

/** Cuerpo de creación. El PDF no existe todavía: no hay nada más que enviar. */
export function toReportCreateInput(state: ReportFormState, tenantId: string): ReportCreateInput {
  const summary = state.summary.trim();
  return {
    tenant_id: tenantId,
    asset_id: state.assetId,
    name: state.name.trim(),
    report_type: state.reportType,
    summary: summary === "" ? null : summary,
  };
}

/** PATCH acepta nombre, estado, resumen, metadatos y fecha de generación. */
export function toReportUpdateInput(state: ReportFormState): ReportUpdateInput {
  const summary = state.summary.trim();
  return {
    name: state.name.trim(),
    status: state.status,
    summary: summary === "" ? null : summary,
  };
}
