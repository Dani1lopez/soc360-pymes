import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import type { VulnerabilityListFilters } from "@/api/schema";
import {
  VULNERABILITIES_PAGE_SIZE,
  fetchVulnerability,
  listVulnerabilities,
} from "../api/vulnerabilities-api";

export const vulnerabilitiesKeys = {
  all: ["vulnerabilities"] as const,
  list: (
    offset: number,
    scanId: string | null,
    { status, severity }: VulnerabilityListFilters = {},
  ) => ["vulnerabilities", "list", { offset, scanId, status, severity }] as const,
  detail: (id: string) => ["vulnerabilities", "detail", id] as const,
};

export function vulnerabilitiesQueryOptions(
  offset: number,
  scanId: string | null = null,
  limit = VULNERABILITIES_PAGE_SIZE,
  filters: VulnerabilityListFilters = {},
) {
  return queryOptions({
    queryKey: vulnerabilitiesKeys.list(offset, scanId, filters),
    queryFn: () => listVulnerabilities({ offset, limit, scanId, ...filters }),
    placeholderData: keepPreviousData,
  });
}

export function useVulnerabilities(
  offset: number,
  scanId: string | null = null,
  filters: VulnerabilityListFilters = {},
) {
  return useQuery(vulnerabilitiesQueryOptions(offset, scanId, VULNERABILITIES_PAGE_SIZE, filters));
}

export function vulnerabilityQueryOptions(id: string) {
  return queryOptions({
    queryKey: vulnerabilitiesKeys.detail(id),
    queryFn: () => fetchVulnerability(id),
  });
}

export function useVulnerability(id: string) {
  return useQuery(vulnerabilityQueryOptions(id));
}
