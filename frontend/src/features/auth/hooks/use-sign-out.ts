import { useMutation } from "@tanstack/react-query";
import { signOut } from "@/api/session";

export function useSignOut() {
  return useMutation({ mutationFn: signOut });
}
