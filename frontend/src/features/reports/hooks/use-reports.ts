import { keepPreviousData, queryOptions, useQuery } from "@tanstack/react-query";
import { REPORTS_PAGE_SIZE, listReports, type ReportFilters } from "../api/reports-api";

export const reportsKeys = {
  all: ["reports"] as const,
  list: (filters: Omit<ReportFilters, "limit">) => ["reports", "list", filters] as const,
  detail: (id: string) => ["reports", "detail", id] as const,
};

export function reportsQueryOptions(filters: Omit<ReportFilters, "limit">) {
  return queryOptions({
    queryKey: reportsKeys.list(filters),
    queryFn: () => listReports({ ...filters, limit: REPORTS_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
}

export function useReports(filters: Omit<ReportFilters, "limit">) {
  return useQuery(reportsQueryOptions(filters));
}
