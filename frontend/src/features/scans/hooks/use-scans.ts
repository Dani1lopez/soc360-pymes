import { useRef } from "react";
import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import { SCANS_PAGE_SIZE, fetchScan, listScans } from "../api/scans-api";
import { SCAN_POLL_BASE_MS, isActiveScan, nextPollDelay, pollingInterval } from "../lib/polling";

export const scansKeys = {
  all: ["scans"] as const,
  list: (offset: number, assetId: string | null) => ["scans", "list", { offset, assetId }] as const,
  detail: (id: string) => ["scans", "detail", id] as const,
};

export function scansQueryOptions(
  offset: number,
  assetId: string | null = null,
  limit = SCANS_PAGE_SIZE,
) {
  return queryOptions({
    queryKey: scansKeys.list(offset, assetId),
    queryFn: () => listScans({ offset, limit, assetId }),
    placeholderData: keepPreviousData,
  });
}

/**
 * Listado con sondeo mientras haya escaneos abiertos. El intervalo crece en
 * cada refresco hasta 30 s y vuelve a 5 s cuando no queda nada abierto; en una
 * pestaña oculta no se sondea (`refetchIntervalInBackground` sigue en `false`).
 *
 * El backoff vive en una ref que se avanza dentro de `refetchInterval`: ese
 * callback se ejecuta al programar el siguiente sondeo, no durante el render,
 * así que no hace falta un efecto que provoque un render extra.
 */
export function useScans(offset: number, assetId: string | null = null) {
  const delayRef = useRef(SCAN_POLL_BASE_MS);
  return useQuery({
    ...scansQueryOptions(offset, assetId),
    refetchInterval: (current) => {
      const items = current.state.data?.items;
      const delay = delayRef.current;
      const interval = pollingInterval(items, delay);
      delayRef.current = interval === false ? SCAN_POLL_BASE_MS : nextPollDelay(delay);
      return interval;
    },
  });
}

export function scanQueryOptions(id: string) {
  return queryOptions({ queryKey: scansKeys.detail(id), queryFn: () => fetchScan(id) });
}

/** Detalle con sondeo fijo de 5 s mientras el escaneo siga abierto. */
export function useScan(id: string) {
  return useQuery({
    ...scanQueryOptions(id),
    refetchInterval: (current) =>
      current.state.data !== undefined && isActiveScan(current.state.data.status)
        ? SCAN_POLL_BASE_MS
        : false,
  });
}
