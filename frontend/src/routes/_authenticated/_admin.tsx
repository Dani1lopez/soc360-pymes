import { createFileRoute, Outlet } from "@tanstack/react-router";
import { requireRoles, ADMIN_ROLES } from "@/features/auth";

export const Route = createFileRoute("/_authenticated/_admin")({
  beforeLoad: ({ context }) => requireRoles(context.user, ADMIN_ROLES),
  component: Outlet,
});
