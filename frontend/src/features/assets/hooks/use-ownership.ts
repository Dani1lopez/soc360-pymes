import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type { OwnershipMethod } from "@/api/schema";
import {
  declareOwnership,
  listOwnership,
  revokeOwnership,
  verifyOwnership,
} from "../api/ownership-api";

export const ownershipKeys = {
  all: ["ownership"] as const,
  asset: (assetId: string) => ["ownership", assetId] as const,
};

export function ownershipQueryOptions(assetId: string) {
  return queryOptions({
    queryKey: ownershipKeys.asset(assetId),
    queryFn: () => listOwnership(assetId),
    // El estado por activo se relee al cambiar de página sin parpadeo.
    placeholderData: keepPreviousData,
  });
}

export function useOwnership(assetId: string) {
  return useQuery(ownershipQueryOptions(assetId));
}

/**
 * Las cuatro acciones comparten el mismo refresco: la lista de declaraciones del
 * activo. No se invalida `assetsKeys` porque declarar no cambia la fila del
 * activo, solo su autorización.
 */
function useOwnershipMutation<TArgs>(
  assetId: string,
  mutationFn: (args: TArgs) => Promise<unknown>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ownershipKeys.asset(assetId) }),
  });
}

export function useDeclareOwnership(assetId: string) {
  return useOwnershipMutation(assetId, (method: OwnershipMethod) =>
    declareOwnership(assetId, method),
  );
}

export function useVerifyOwnership(assetId: string) {
  return useOwnershipMutation(assetId, () => verifyOwnership(assetId));
}

export function useRevokeOwnership(assetId: string) {
  return useOwnershipMutation(assetId, () => revokeOwnership(assetId));
}
