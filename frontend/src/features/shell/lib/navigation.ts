import type { Role, UserResponse } from "@/api/schema";
import { ADMIN_ROLES, READ_ROLES, hasAnyRole } from "@/features/auth";

type NavigationItem = {
  label: string;
  to: "/" | "/assets" | "/scans" | "/vulnerabilities" | "/reports" | "/users" | "/settings";
  allowed: readonly Role[];
};
export const NAV_ITEMS: readonly NavigationItem[] = [
  { label: "Panel", to: "/", allowed: READ_ROLES },
  { label: "Activos", to: "/assets", allowed: READ_ROLES },
  { label: "Escaneos", to: "/scans", allowed: READ_ROLES },
  { label: "Vulnerabilidades", to: "/vulnerabilities", allowed: READ_ROLES },
  { label: "Informes", to: "/reports", allowed: READ_ROLES },
  { label: "Usuarios", to: "/users", allowed: ADMIN_ROLES },
  { label: "Configuración", to: "/settings", allowed: ADMIN_ROLES },
];

export function navigationFor(user: Pick<UserResponse, "role">) {
  return NAV_ITEMS.filter((item) => hasAnyRole(user, item.allowed));
}
