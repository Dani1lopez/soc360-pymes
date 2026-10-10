import {
  FileText,
  LayoutDashboard,
  Radar,
  Server,
  Settings,
  ShieldAlert,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Role, UserResponse } from "@/api/schema";
import { ADMIN_ROLES, READ_ROLES, hasAnyRole } from "@/features/auth";

type NavigationItem = {
  label: string;
  to: "/" | "/assets" | "/scans" | "/vulnerabilities" | "/reports" | "/users" | "/settings";
  allowed: readonly Role[];
  icon: LucideIcon;
};
export const NAV_ITEMS: readonly NavigationItem[] = [
  { label: "Panel", to: "/", allowed: READ_ROLES, icon: LayoutDashboard },
  { label: "Activos", to: "/assets", allowed: READ_ROLES, icon: Server },
  { label: "Escaneos", to: "/scans", allowed: READ_ROLES, icon: Radar },
  { label: "Vulnerabilidades", to: "/vulnerabilities", allowed: READ_ROLES, icon: ShieldAlert },
  { label: "Informes", to: "/reports", allowed: READ_ROLES, icon: FileText },
  { label: "Usuarios", to: "/users", allowed: ADMIN_ROLES, icon: Users },
  { label: "Configuración", to: "/settings", allowed: ADMIN_ROLES, icon: Settings },
];

export function navigationFor(user: Pick<UserResponse, "role">) {
  return NAV_ITEMS.filter((item) => hasAnyRole(user, item.allowed));
}
