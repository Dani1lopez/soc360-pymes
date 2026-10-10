import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/features/shell";
export const Route = createFileRoute("/_authenticated/_reader/scans")({
  component: () => <PlaceholderPage title="Escaneos" />,
});
