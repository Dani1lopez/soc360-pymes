import type { ScanCreateInput, ScanResponse, ScanType, ScanUpdateInput } from "@/api/schema";
import { joinList, splitList } from "./scan-labels";

/** Estado del formulario de alta y edición, en texto: la conversión a la
 * configuración del backend la hace `toScanCreateInput`/`toScanUpdateInput`. */
export type ScanFormState = {
  name: string;
  type: ScanType;
  assetId: string;
  hostDiscovery: boolean;
  /** Comprobaciones separadas por comas (vulnerability y full). */
  checks: string;
  /** Rutas separadas por comas (web y full). */
  paths: string;
};

export const DEFAULT_CHECKS = "tls, headers";
export const DEFAULT_PATHS = "/";

export function emptyScanForm(assetId = ""): ScanFormState {
  return {
    name: "",
    type: "discovery",
    assetId,
    hostDiscovery: true,
    checks: DEFAULT_CHECKS,
    paths: DEFAULT_PATHS,
  };
}

export function formFromScan(scan: ScanResponse): ScanFormState {
  const config = (scan.config ?? {}) as Record<string, unknown>;
  return {
    name: scan.name,
    type: scan.type,
    assetId: scan.asset_id,
    hostDiscovery: config.host_discovery === undefined ? true : config.host_discovery === true,
    checks: joinList(config.checks) || DEFAULT_CHECKS,
    paths: joinList(config.paths) || DEFAULT_PATHS,
  };
}

export function needsChecks(type: ScanType): boolean {
  return type === "vulnerability" || type === "full";
}

export function needsPaths(type: ScanType): boolean {
  return type === "web" || type === "full";
}

export function needsHostDiscovery(type: ScanType): boolean {
  return type === "discovery" || type === "full";
}

export type ScanFormErrors = Partial<Record<"name" | "assetId" | "checks" | "paths", string>>;

/** Validación de forma alineada con `app/modules/scans/service.py`. */
export function validateScanForm(state: ScanFormState): ScanFormErrors {
  const errors: ScanFormErrors = {};
  const name = state.name.trim();
  if (name === "") errors.name = "Introduce un nombre.";
  else if (name.length > 255) errors.name = "El nombre no puede superar 255 caracteres.";
  if (state.assetId === "") errors.assetId = "Selecciona un activo.";
  if (needsChecks(state.type) && splitList(state.checks).length === 0) {
    errors.checks = "Añade al menos una comprobación.";
  }
  if (needsPaths(state.type) && splitList(state.paths).length === 0) {
    errors.paths = "Añade al menos una ruta.";
  }
  return errors;
}

export function hasScanFormErrors(errors: ScanFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

function configFor(state: ScanFormState): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  if (needsHostDiscovery(state.type)) config.host_discovery = state.hostDiscovery;
  if (needsChecks(state.type)) config.checks = splitList(state.checks);
  if (needsPaths(state.type)) config.paths = splitList(state.paths);
  return config;
}

/** Cuerpo de creación; la unión se arma por rama para conservar el literal. */
export function toScanCreateInput(state: ScanFormState, tenantId: string): ScanCreateInput {
  const shared = { asset_id: state.assetId, name: state.name.trim(), tenant_id: tenantId };
  switch (state.type) {
    case "discovery":
      return { ...shared, type: "discovery", config: { host_discovery: state.hostDiscovery } };
    case "vulnerability":
      return { ...shared, type: "vulnerability", config: { checks: splitList(state.checks) } };
    case "web":
      return { ...shared, type: "web", config: { paths: splitList(state.paths) } };
    case "full":
      return {
        ...shared,
        type: "full",
        config: {
          host_discovery: state.hostDiscovery,
          checks: splitList(state.checks),
          paths: splitList(state.paths),
        },
      };
  }
}

/** Cuerpo de actualización: el activo no se puede cambiar por PATCH. */
export function toScanUpdateInput(state: ScanFormState): ScanUpdateInput {
  return { name: state.name.trim(), type: state.type, config: configFor(state) };
}
