import { createFileRoute, Outlet } from "@tanstack/react-router";
import { requireRoles, READ_ROLES } from "@/features/auth";

export const Route = createFileRoute("/_authenticated/_reader")({
  beforeLoad: ({ context }) => requireRoles(context.user, READ_ROLES),
  component: Outlet,
});
