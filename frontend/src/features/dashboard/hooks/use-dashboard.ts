import { queryOptions, useQuery } from "@tanstack/react-query";
import { useCurrentUser, useEffectiveTenantId } from "@/features/auth";
import { fetchDashboardSummary } from "../api/dashboard-api";

export const dashboardQueryKey = ["dashboard", "summary"] as const;

export function dashboardQueryOptions(tenantId?: string) {
  return queryOptions({
    queryKey: [...dashboardQueryKey, tenantId ?? "own"],
    queryFn: () => fetchDashboardSummary(tenantId),
    // Agregado por tenant: cambia despacio, y `generated_at` dice su frescura.
    staleTime: 60_000,
  });
}

export function useDashboardSummary() {
  const { data: user } = useCurrentUser();
  const effectiveTenantId = useEffectiveTenantId();
  const tenantId = user?.is_superadmin ? (effectiveTenantId ?? undefined) : undefined;
  return useQuery({
    ...dashboardQueryOptions(tenantId),
    enabled: user !== undefined && (!user.is_superadmin || effectiveTenantId !== null),
  });
}
