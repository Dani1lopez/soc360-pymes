import type { ScanResponse, ScanStatus, ScanType } from "@/api/schema";

export const SCAN_TYPES = [
  "discovery",
  "vulnerability",
  "web",
  "full",
] as const satisfies readonly ScanType[];

const TYPE_LABELS: Record<ScanType, string> = {
  discovery: "Descubrimiento",
  vulnerability: "Vulnerabilidades",
  web: "Aplicación web",
  full: "Completo",
};

const STATUS_LABELS: Record<ScanStatus, string> = {
  pending: "Pendiente",
  running: "En ejecución",
  completed: "Completado",
  failed: "Fallido",
  cancelled: "Cancelado",
};

/** Tono por estado con los tokens semánticos del tema. */
const STATUS_TONES: Record<ScanStatus, string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-primary/10 text-primary",
  completed: "bg-sev-ok-tint text-sev-ok-foreground",
  failed: "bg-sev-critical-tint text-sev-critical-foreground",
  cancelled: "bg-secondary text-secondary-foreground",
};

function isScanType(value: string): value is ScanType {
  return Object.hasOwn(TYPE_LABELS, value);
}

function isScanStatus(value: string): value is ScanStatus {
  return Object.hasOwn(STATUS_LABELS, value);
}

/** Etiquetas tolerantes a valores fuera del enum: nunca rompen la tabla. */
export function scanTypeLabel(type: string): string {
  return isScanType(type) ? TYPE_LABELS[type] : type;
}

export function scanStatusLabel(status: string): string {
  return isScanStatus(status) ? STATUS_LABELS[status] : "Desconocido";
}

export function scanStatusTone(status: string): string {
  return isScanStatus(status) ? STATUS_TONES[status] : "bg-muted text-muted-foreground";
}

/** Resumen legible de la configuración, sin enseñar el JSON crudo en la tabla. */
export function scanConfigSummary(config: unknown): string {
  if (config === null || typeof config !== "object") return "—";
  const entries = Object.entries(config as Record<string, unknown>);
  if (entries.length === 0) return "—";
  return entries
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

/** Lista de textos separados por comas, sin vacíos ni duplicados. */
export function splitList(value: string): string[] {
  const items = value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "");
  return [...new Set(items)];
}

export function joinList(values: unknown): string {
  return Array.isArray(values) ? values.join(", ") : "";
}

/** ¿Se puede ejecutar o cancelar ya? Mismo criterio que el backend. */
export function canRunScan(scan: Pick<ScanResponse, "status">): boolean {
  return scan.status === "pending";
}

export function canCancelScan(scan: Pick<ScanResponse, "status">): boolean {
  return scan.status === "pending" || scan.status === "running";
}
