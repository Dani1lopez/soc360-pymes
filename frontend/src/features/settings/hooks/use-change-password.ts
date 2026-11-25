import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { clearSession } from "@/api/session";
import { changePassword } from "../api/settings-api";

export function useChangePassword() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: changePassword,
    onSuccess: () => {
      clearSession();
      queryClient.clear();
      void navigate({ to: "/login", replace: true });
    },
  });
}
