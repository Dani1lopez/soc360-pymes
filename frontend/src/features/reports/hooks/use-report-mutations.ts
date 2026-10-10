import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import type { ReportUpdateInput } from "@/api/schema";
import { createReport, deleteReport, updateReport } from "../api/reports-api";
import { reportsKeys } from "./use-reports";

function invalidate(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: reportsKeys.all });
}

export function useCreateReport() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: createReport, onSuccess: () => invalidate(queryClient) });
}

export function useUpdateReport() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: ReportUpdateInput }) =>
      updateReport(id, input),
    onSuccess: () => invalidate(queryClient),
  });
}

export function useDeleteReport() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: deleteReport, onSuccess: () => invalidate(queryClient) });
}
