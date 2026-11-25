import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { TenantUpdateInput } from "@/api/schema";
import { fetchTenant, listTenants, updateTenant } from "../api/tenants-api";

export const tenantsKeys = {
  all: ["tenants"] as const,
  list: ["tenants", "list"] as const,
  detail: (id: string) => ["tenants", "detail", id] as const,
};

export function tenantsQueryOptions() {
  return queryOptions({
    queryKey: tenantsKeys.list,
    queryFn: listTenants,
    staleTime: 60_000,
  });
}

/**
 * Organizaciones para selectores. `enabled` evita la llamada —que es solo para
 * superadministradores— cuando quien mira la página no lo es.
 */
export function useTenants({ enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ ...tenantsQueryOptions(), enabled });
}

export function tenantQueryOptions(id: string) {
  return queryOptions({ queryKey: tenantsKeys.detail(id), queryFn: () => fetchTenant(id) });
}

export function useTenant(id: string) {
  return useQuery(tenantQueryOptions(id));
}

export function useUpdateTenant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: TenantUpdateInput }) =>
      updateTenant(id, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tenantsKeys.all }),
  });
}
