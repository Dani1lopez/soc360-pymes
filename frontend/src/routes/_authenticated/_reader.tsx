import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ErrorPage } from "@/components/error-page";
import { requireRoles, READ_ROLES } from "@/features/auth";

export const Route = createFileRoute("/_authenticated/_reader")({
  beforeLoad: ({ context }) => requireRoles(context.user, READ_ROLES),
  component: Outlet,
  // Un fallo de una página de lectura no es un fallo de sesión: se resuelve aquí.
  errorComponent: ErrorPage,
});
