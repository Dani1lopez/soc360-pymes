import { createFileRoute } from "@tanstack/react-router";
import { PlaceholderPage } from "@/features/shell";
export const Route = createFileRoute("/_authenticated/_reader/vulnerabilities")({
  component: () => <PlaceholderPage title="Vulnerabilidades" />,
});
