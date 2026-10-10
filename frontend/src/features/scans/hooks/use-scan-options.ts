import { queryOptions, useQuery } from "@tanstack/react-query";
import type { ScanResponse } from "@/api/schema";
import { listScans } from "../api/scans-api";

/** Tope de la API: la lista para selectores y mapas no pagina. */
export const SCAN_OPTIONS_LIMIT = 200;

/**
 * Escaneos para selectores y para resolver `scan_id` a su nombre y a su activo.
 * Sin sondeo: aquí no interesa el estado en vivo, solo el catálogo.
 */
export function scanOptionsQueryOptions() {
  return queryOptions({
    queryKey: ["scans", "options"] as const,
    queryFn: () => listScans({ offset: 0, limit: SCAN_OPTIONS_LIMIT }),
    staleTime: 60_000,
  });
}

export function useScanOptions() {
  return useQuery(scanOptionsQueryOptions());
}

/** Mapa `scan_id` → `asset_id`, el único camino de un hallazgo a su activo. */
export function scanAssetIds(
  scans: Pick<ScanResponse, "id" | "asset_id">[] | undefined,
): Record<string, string> {
  const byId: Record<string, string> = {};
  for (const scan of scans ?? []) byId[scan.id] = scan.asset_id;
  return byId;
}

/** Mapa `scan_id` → nombre del escaneo. */
export function scanNamesById(
  scans: Pick<ScanResponse, "id" | "name">[] | undefined,
): Record<string, string> {
  const byId: Record<string, string> = {};
  for (const scan of scans ?? []) byId[scan.id] = scan.name;
  return byId;
}
