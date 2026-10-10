import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { ScanUpdateInput } from "@/api/schema";
import { cancelScan, createScan, deleteScan, runScan, updateScan } from "../api/scans-api";
import { scansKeys } from "./use-scans";

function invalidateScans(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: scansKeys.all });
}

export function useCreateScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createScan,
    onSuccess: () => invalidateScans(queryClient),
  });
}

export function useUpdateScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ScanUpdateInput }) => updateScan(id, input),
    onSuccess: () => invalidateScans(queryClient),
  });
}

export function useDeleteScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteScan,
    onSuccess: () => invalidateScans(queryClient),
  });
}

export function useRunScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: runScan,
    onSuccess: () => invalidateScans(queryClient),
  });
}

export function useCancelScan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: cancelScan,
    onSuccess: () => invalidateScans(queryClient),
  });
}
