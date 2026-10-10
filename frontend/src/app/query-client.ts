import { QueryClient } from "@tanstack/react-query";
import { isApiError } from "@/api/errors";

/**
 * Retry a failed query once, and only when another attempt can succeed:
 * transport failures, 5xx and unexpected errors. A 4xx answer will not change.
 */
export function shouldRetryQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= 1) return false;
  if (!isApiError(error)) return true;
  return error.kind === "network" || error.kind === "server" || error.kind === "unavailable";
}

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetryQuery, refetchOnWindowFocus: false, staleTime: 30_000 },
    },
  });
}
