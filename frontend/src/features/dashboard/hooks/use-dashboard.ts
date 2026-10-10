import { queryOptions, useQuery } from "@tanstack/react-query";
import { fetchDashboardSummary } from "../api/dashboard-api";

export const dashboardQueryKey = ["dashboard", "summary"] as const;

export function dashboardQueryOptions() {
  return queryOptions({
    queryKey: dashboardQueryKey,
    queryFn: fetchDashboardSummary,
    // Agregado por tenant: cambia despacio, y `generated_at` dice su frescura.
    staleTime: 60_000,
  });
}

export function useDashboardSummary() {
  return useQuery(dashboardQueryOptions());
}
