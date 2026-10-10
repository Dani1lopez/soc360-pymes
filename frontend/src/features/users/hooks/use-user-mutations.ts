import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { UserUpdateInput } from "@/api/schema";
import { createUser, deleteUser, updateUser } from "../api/users-api";
import { usersKeys } from "./use-users";

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createUser,
    onSuccess: () => client.invalidateQueries({ queryKey: usersKeys.all }),
  });
}

export function useUpdateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UserUpdateInput }) => updateUser(id, input),
    onSuccess: () => client.invalidateQueries({ queryKey: usersKeys.all }),
  });
}

export function useDeactivateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deleteUser,
    onSuccess: () => client.invalidateQueries({ queryKey: usersKeys.all }),
  });
}

export function useReactivateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => updateUser(id, { is_active: true }),
    onSuccess: () => client.invalidateQueries({ queryKey: usersKeys.all }),
  });
}
