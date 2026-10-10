import { apiFetch } from "@/api/client";
import type {
  VulnerabilityCreateInput,
  VulnerabilityList,
  VulnerabilityResponse,
  VulnerabilityUpdateInput,
} from "@/api/schema";

const BASE = "/api/v1/vulnerabilities";

/** Tamaño de página de la tabla (el backend admite de 1 a 200). */
export const VULNERABILITIES_PAGE_SIZE = 20;

/**
 * Página de hallazgos, filtrable por escaneo. La API no filtra por estado ni
 * por severidad: eso se resuelve en la UI sobre la página cargada.
 */
export function listVulnerabilities({
  offset,
  limit = VULNERABILITIES_PAGE_SIZE,
  scanId,
}: {
  offset: number;
  limit?: number;
  scanId?: string | null;
}): Promise<VulnerabilityList> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (scanId) query.set("scan_id", scanId);
  return apiFetch<VulnerabilityList>(`${BASE}/?${query.toString()}`);
}

export function fetchVulnerability(id: string): Promise<VulnerabilityResponse> {
  return apiFetch<VulnerabilityResponse>(`${BASE}/${id}`);
}

export function createVulnerability(
  input: VulnerabilityCreateInput,
): Promise<VulnerabilityResponse> {
  return apiFetch<VulnerabilityResponse>(`${BASE}/`, { method: "POST", body: input });
}

export function updateVulnerability(
  id: string,
  input: VulnerabilityUpdateInput,
): Promise<VulnerabilityResponse> {
  return apiFetch<VulnerabilityResponse>(`${BASE}/${id}`, { method: "PATCH", body: input });
}

export function deleteVulnerability(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" });
}
