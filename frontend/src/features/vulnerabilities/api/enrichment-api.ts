import { apiFetch } from "@/api/client";
import type { EnrichmentQueued, ScanEnrichmentQueued, VulnerabilityEnrichment } from "@/api/schema";

/** Un ítem por función de enriquecimiento, con su estado y su contenido. */
export function fetchVulnerabilityEnrichment(
  vulnerabilityId: string,
): Promise<VulnerabilityEnrichment> {
  return apiFetch<VulnerabilityEnrichment>(`/api/v1/vulnerabilities/${vulnerabilityId}/enrichment`);
}

/** Encola el enriquecimiento de un hallazgo (admin, analyst o superadmin). */
export function relaunchVulnerabilityEnrichment(
  vulnerabilityId: string,
): Promise<EnrichmentQueued> {
  return apiFetch<EnrichmentQueued>(`/api/v1/vulnerabilities/${vulnerabilityId}/enrichment`, {
    method: "POST",
  });
}

/** Encola el enriquecimiento de todos los hallazgos pendientes del escaneo. */
export function relaunchScanEnrichment(scanId: string): Promise<ScanEnrichmentQueued> {
  return apiFetch<ScanEnrichmentQueued>(`/api/v1/scans/${scanId}/enrichment`, {
    method: "POST",
  });
}
