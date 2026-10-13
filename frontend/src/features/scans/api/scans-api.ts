import { apiFetch } from "@/api/client";
import type { ScanCreateInput, ScanList, ScanResponse, ScanUpdateInput } from "@/api/schema";

const BASE = "/api/v1/scans";

/** Tamaño de página de la tabla (el backend admite de 1 a 200). */
export const SCANS_PAGE_SIZE = 20;

/** Página de escaneos, opcionalmente filtrada por activo. */
export function listScans({
  offset,
  limit = SCANS_PAGE_SIZE,
  assetId,
}: {
  offset: number;
  limit?: number;
  assetId?: string | null;
}): Promise<ScanList> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (assetId) query.set("asset_id", assetId);
  return apiFetch<ScanList>(`${BASE}/?${query.toString()}`);
}

export function fetchScan(id: string): Promise<ScanResponse> {
  return apiFetch<ScanResponse>(`${BASE}/${id}`);
}

export function createScan(input: ScanCreateInput): Promise<ScanResponse> {
  return apiFetch<ScanResponse>(`${BASE}/`, { method: "POST", body: input });
}

export function updateScan(id: string, input: ScanUpdateInput): Promise<ScanResponse> {
  return apiFetch<ScanResponse>(`${BASE}/${id}`, { method: "PATCH", body: input });
}

export function deleteScan(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" });
}

/**
 * Encola la ejecución: responde 202 con el escaneo ya despachado. El backend
 * rechaza con 409 lo que no esté pendiente y con 403 si el interruptor de
 * ejecución está apagado.
 */
export function runScan(id: string): Promise<ScanResponse> {
  return apiFetch<ScanResponse>(`${BASE}/${id}/run`, { method: "POST" });
}

/** Cancela un escaneo pendiente o en ejecución (409 si ya terminó). */
export function cancelScan(id: string): Promise<ScanResponse> {
  return apiFetch<ScanResponse>(`${BASE}/${id}/cancel`, { method: "POST" });
}
