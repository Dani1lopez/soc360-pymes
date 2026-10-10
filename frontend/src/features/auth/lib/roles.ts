import type { Role, UserResponse } from "@/api/schema";

// Mirrors the backend `require_any_role` allowlists: exact role match, no
// hierarchy and no `is_superadmin` shortcut. `ingestor` is a machine role.
export const READ_ROLES: readonly Role[] = ["viewer", "analyst", "admin", "superadmin"];
export const ADMIN_ROLES: readonly Role[] = ["admin", "superadmin"];

export function roleLabel(role: Role): string {
  const labels: Record<Role, string> = {
    viewer: "Lector",
    analyst: "Analista",
    ingestor: "Ingesta",
    admin: "Administrador",
    superadmin: "Superadministrador",
  };
  return labels[role];
}

export function hasAnyRole(
  user: Pick<UserResponse, "role"> | null | undefined,
  allowed: readonly Role[],
): boolean {
  return user != null && allowed.includes(user.role);
}
