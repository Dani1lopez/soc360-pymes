import { apiFetch } from "@/api/client";
import type { AssetCreateInput, AssetList, AssetResponse, AssetUpdateInput } from "@/api/schema";

const BASE = "/api/v1/assets";

/** Tamaño de página de la tabla (el backend admite de 1 a 200). */
export const ASSETS_PAGE_SIZE = 20;

/** Página de activos visibles para el usuario. */
export function listAssets({
  offset,
  limit = ASSETS_PAGE_SIZE,
}: {
  offset: number;
  limit?: number;
}): Promise<AssetList> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return apiFetch<AssetList>(`${BASE}/?${query.toString()}`);
}

export function fetchAsset(id: string): Promise<AssetResponse> {
  return apiFetch<AssetResponse>(`${BASE}/${id}`);
}

export function createAsset(input: AssetCreateInput): Promise<AssetResponse> {
  return apiFetch<AssetResponse>(`${BASE}/`, { method: "POST", body: input });
}

export function updateAsset(id: string, input: AssetUpdateInput): Promise<AssetResponse> {
  return apiFetch<AssetResponse>(`${BASE}/${id}`, { method: "PATCH", body: input });
}

export function deleteAsset(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" });
}

/**
 * Exportación CSV completa. Comparte ruta con el listado, así que la respuesta
 * se lee como texto y no como JSON.
 */
export function exportAssetsCsv(): Promise<string> {
  return apiFetch<string>(`${BASE}/?export=csv`, { parseAs: "text" });
}
