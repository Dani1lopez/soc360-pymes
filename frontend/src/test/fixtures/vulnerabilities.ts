import type {
  EnrichmentItem,
  VulnerabilityEnrichment,
  VulnerabilityList,
  VulnerabilityResponse,
} from "@/api/schema";

export function makeVulnerability(
  overrides: Partial<VulnerabilityResponse> = {},
): VulnerabilityResponse {
  return {
    id: "00000000-0000-4000-8000-000000000301",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    scan_id: "00000000-0000-4000-8000-000000000201",
    title: "Inyección SQL en el buscador",
    description: "El parámetro q concatena la entrada del usuario.",
    severity: "critical",
    status: "open",
    closed_at: null,
    cve_id: "CVE-2026-12345",
    cvss_score: 9.8,
    vulnerability_metadata: { endpoint: "/search" },
    created_at: "2026-10-09T07:00:00Z",
    updated_at: "2026-10-09T07:05:00Z",
    ...overrides,
  };
}

export function vulnerabilityList(
  items: VulnerabilityResponse[],
  { total = items.length, limit = 20, offset = 0 }: Partial<Omit<VulnerabilityList, "items">> = {},
): VulnerabilityList {
  return { items, total, limit, offset };
}

export function makeEnrichmentItem(overrides: Partial<EnrichmentItem> = {}): EnrichmentItem {
  return {
    function: "summary",
    status: "ok",
    content: "Resumen generado del hallazgo.",
    error: null,
    model: "gpt-test",
    prompt_version: "v1",
    attempts: 1,
    updated_at: "2026-10-09T07:06:00Z",
    ...overrides,
  };
}

export function makeEnrichment(
  items: EnrichmentItem[],
  overrides: Partial<VulnerabilityEnrichment> = {},
): VulnerabilityEnrichment {
  return {
    vulnerability_id: "00000000-0000-4000-8000-000000000301",
    level: "standard",
    items,
    ...overrides,
  };
}
