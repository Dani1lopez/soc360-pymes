import { useQuery } from "@tanstack/react-query";
import { listUsers, type UsersFilters } from "../api/users-api";

export const usersKeys = {
  all: ["users"] as const,
  list: ({ includeInactive, tenantId }: UsersFilters) =>
    ["users", "list", { includeInactive, tenantId: tenantId ?? null }] as const,
};

export function useUsers(filters: UsersFilters, { enabled = true } = {}) {
  // Array plano, sin total: cargamos hasta 200 cuentas, sin paginación.
  return useQuery({
    queryKey: usersKeys.list(filters),
    queryFn: () => listUsers(filters),
    enabled,
  });
}
