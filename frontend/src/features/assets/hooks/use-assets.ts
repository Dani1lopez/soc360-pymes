import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import { ASSETS_PAGE_SIZE, listAssets } from "../api/assets-api";

export const assetsKeys = {
  /** Prefijo de toda la feature: invalidar aquí refresca cualquier página. */
  all: ["assets"] as const,
  list: (offset: number, limit: number) => ["assets", "list", { offset, limit }] as const,
};

export function assetsQueryOptions(offset: number, limit = ASSETS_PAGE_SIZE) {
  return queryOptions({
    queryKey: assetsKeys.list(offset, limit),
    queryFn: () => listAssets({ offset, limit }),
    // Mantiene la página anterior mientras llega la siguiente: sin parpadeo.
    placeholderData: keepPreviousData,
  });
}

export function useAssets(offset: number, limit = ASSETS_PAGE_SIZE) {
  return useQuery(assetsQueryOptions(offset, limit));
}
