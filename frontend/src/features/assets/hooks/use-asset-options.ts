import { queryOptions, useQuery } from "@tanstack/react-query";
import { listAssets } from "../api/assets-api";

/** Tope de la API: el selector de activos no pagina. */
export const ASSET_OPTIONS_LIMIT = 200;

/**
 * Activos para selectores y para resolver `asset_id` a su valor legible.
 * Lista corta y cacheada: cambia poco y la comparten varias páginas.
 */
export function assetOptionsQueryOptions() {
  return queryOptions({
    queryKey: ["assets", "options"] as const,
    queryFn: () => listAssets({ offset: 0, limit: ASSET_OPTIONS_LIMIT }),
    staleTime: 60_000,
  });
}

export function useAssetOptions() {
  return useQuery(assetOptionsQueryOptions());
}

/** Mapa id → valor para mostrar el activo de un escaneo o informe. */
export function assetValuesById(
  assets: { id: string; value: string }[] | undefined,
): Record<string, string> {
  const byId: Record<string, string> = {};
  for (const asset of assets ?? []) byId[asset.id] = asset.value;
  return byId;
}
