import { apiFetch } from "@/api/client";
import type { UserCreateInput, UserResponse, UserUpdateInput } from "@/api/schema";

const BASE = "/api/v1/users";

export type UsersFilters = { includeInactive: boolean; tenantId?: string | null };

export function listUsers({ includeInactive, tenantId }: UsersFilters): Promise<UserResponse[]> {
  const query = new URLSearchParams({
    include_inactive: String(includeInactive),
    offset: "0",
    limit: "200",
  });
  if (tenantId) query.set("tenant_id", tenantId);
  return apiFetch<UserResponse[]>(`${BASE}/?${query.toString()}`);
}

export function createUser(input: UserCreateInput): Promise<UserResponse> {
  return apiFetch<UserResponse>(`${BASE}/`, { method: "POST", body: input });
}

export function updateUser(id: string, input: UserUpdateInput): Promise<UserResponse> {
  return apiFetch<UserResponse>(`${BASE}/${id}`, { method: "PATCH", body: input });
}

/** Desactiva la cuenta; no la borra. */
export function deleteUser(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" });
}
