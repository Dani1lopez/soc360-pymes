import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchVulnerabilityEnrichment,
  relaunchScanEnrichment,
  relaunchVulnerabilityEnrichment,
} from "../api/enrichment-api";
import { hasPendingEnrichment } from "../lib/vulnerability-labels";

/** Intervalo de refresco mientras queda trabajo en cola. */
export const ENRICHMENT_POLL_MS = 5_000;

export const enrichmentKeys = {
  all: ["enrichment"] as const,
  vulnerability: (id: string) => ["enrichment", "vulnerability", id] as const,
};

export function enrichmentQueryOptions(id: string) {
  return queryOptions({
    queryKey: enrichmentKeys.vulnerability(id),
    queryFn: () => fetchVulnerabilityEnrichment(id),
    // Sondea solo mientras alguna función siga en cola: el trabajo es asíncrono.
    refetchInterval: (current) =>
      hasPendingEnrichment(current.state.data?.items) ? ENRICHMENT_POLL_MS : false,
  });
}

export function useVulnerabilityEnrichment(id: string) {
  return useQuery(enrichmentQueryOptions(id));
}

export function useRelaunchVulnerabilityEnrichment(vulnerabilityId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => relaunchVulnerabilityEnrichment(vulnerabilityId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: enrichmentKeys.all }),
  });
}

export function useRelaunchScanEnrichment(scanId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => relaunchScanEnrichment(scanId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: enrichmentKeys.all }),
  });
}
