import { createFileRoute, Outlet } from "@tanstack/react-router";

// Ruta de layout: el listado y el detalle cuelgan de aquí.
export const Route = createFileRoute("/_authenticated/_reader/vulnerabilities")({
  component: Outlet,
});
