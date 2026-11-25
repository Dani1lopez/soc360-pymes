import type { ReportStatus, ReportType } from "@/api/schema";

export const REPORT_TYPES = [
  "vulnerability",
  "executive",
  "technical",
  "compliance",
] as const satisfies readonly ReportType[];

export const REPORT_STATUSES = [
  "pending",
  "generating",
  "completed",
  "failed",
] as const satisfies readonly ReportStatus[];

const TYPE_LABELS: Record<ReportType, string> = {
  vulnerability: "Vulnerabilidades",
  executive: "Ejecutivo",
  technical: "Técnico",
  compliance: "Cumplimiento",
};

const STATUS_LABELS: Record<ReportStatus, string> = {
  pending: "Pendiente",
  generating: "Generándose",
  completed: "Completado",
  failed: "Fallido",
};

const STATUS_TONES: Record<ReportStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  generating: "bg-primary/10 text-primary",
  completed: "bg-sev-ok-tint text-sev-ok-foreground",
  failed: "bg-sev-critical-tint text-sev-critical-foreground",
};

function isReportType(value: string): value is ReportType {
  return Object.hasOwn(TYPE_LABELS, value);
}

function isReportStatus(value: string): value is ReportStatus {
  return Object.hasOwn(STATUS_LABELS, value);
}

/** Etiquetas tolerantes a valores fuera del enum: nunca rompen la tabla. */
export function reportTypeLabel(type: string): string {
  return isReportType(type) ? TYPE_LABELS[type] : type;
}

export function reportStatusLabel(status: string): string {
  return isReportStatus(status) ? STATUS_LABELS[status] : "Desconocido";
}

export function reportStatusTone(status: string): string {
  return isReportStatus(status) ? STATUS_TONES[status] : "bg-muted text-muted-foreground";
}
