import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { AssetUpdateInput } from "@/api/schema";
import { createAsset, deleteAsset, exportAssetsCsv, updateAsset } from "../api/assets-api";
import { assetsKeys } from "./use-assets";

function invalidateAssets(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: assetsKeys.all });
}

export function useCreateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createAsset,
    onSuccess: () => invalidateAssets(queryClient),
  });
}

export function useUpdateAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: AssetUpdateInput }) => updateAsset(id, input),
    onSuccess: () => invalidateAssets(queryClient),
  });
}

export function useDeleteAsset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAsset,
    onSuccess: () => invalidateAssets(queryClient),
  });
}

/** La descarga la materializa quien consuma el hook con `downloadTextFile`. */
export function useExportAssets() {
  return useMutation({ mutationFn: exportAssetsCsv });
}
