import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/features/shell";
export const Route = createFileRoute("/_authenticated/_reader/reports")({
  component: () => <PlaceholderPage title="Informes" />,
});
