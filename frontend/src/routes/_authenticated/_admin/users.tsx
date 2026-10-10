import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/features/shell";
export const Route = createFileRoute("/_authenticated/_admin/users")({
  component: () => <PlaceholderPage title="Usuarios" />,
});
