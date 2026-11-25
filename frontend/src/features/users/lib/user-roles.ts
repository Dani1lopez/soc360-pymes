import type { Role } from "@/api/schema";

export function assignableUserRoles(callerRole: Role | undefined): readonly Role[] {
  if (callerRole === "superadmin") return ["admin", "analyst", "viewer", "ingestor", "superadmin"];
  if (callerRole === "admin") return ["admin", "analyst", "viewer"];
  return [];
}
