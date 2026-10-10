import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ErrorPage } from "@/components/error-page";
import { requireRoles, ADMIN_ROLES } from "@/features/auth";

export const Route = createFileRoute("/_authenticated/_admin")({
  beforeLoad: ({ context }) => requireRoles(context.user, ADMIN_ROLES),
  component: Outlet,
  // Un fallo de una página de administración no es un fallo de sesión.
  errorComponent: ErrorPage,
});
