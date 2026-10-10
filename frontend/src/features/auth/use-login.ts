import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { LoginRequest } from "@/api/schema";
import { login } from "./api";
import { currentUserQueryOptions } from "./use-current-user";

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (credentials: LoginRequest) => {
      await login(credentials);
      await queryClient.prefetchQuery(currentUserQueryOptions());
    },
  });
}
