import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import {
  VULNERABILITIES_PAGE_SIZE,
  fetchVulnerability,
  listVulnerabilities,
} from "../api/vulnerabilities-api";

export const vulnerabilitiesKeys = {
  all: ["vulnerabilities"] as const,
  list: (offset: number, scanId: string | null) =>
    ["vulnerabilities", "list", { offset, scanId }] as const,
  detail: (id: string) => ["vulnerabilities", "detail", id] as const,
};

export function vulnerabilitiesQueryOptions(
  offset: number,
  scanId: string | null = null,
  limit = VULNERABILITIES_PAGE_SIZE,
) {
  return queryOptions({
    queryKey: vulnerabilitiesKeys.list(offset, scanId),
    queryFn: () => listVulnerabilities({ offset, limit, scanId }),
    placeholderData: keepPreviousData,
  });
}

export function useVulnerabilities(offset: number, scanId: string | null = null) {
  return useQuery(vulnerabilitiesQueryOptions(offset, scanId));
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
