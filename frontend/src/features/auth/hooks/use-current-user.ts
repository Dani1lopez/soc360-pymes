import { queryOptions, useQuery } from "@tanstack/react-query";
import { fetchCurrentUser } from "../api/auth-api";

export const currentUserQueryKey = ["auth", "me"] as const;

/** Shared by the hook and the router guards (`ensureQueryData`). */
export function currentUserQueryOptions() {
  return queryOptions({
    queryKey: currentUserQueryKey,
    queryFn: fetchCurrentUser,
    staleTime: 5 * 60_000,
  });
}

export function useCurrentUser() {
  return useQuery(currentUserQueryOptions());
}
