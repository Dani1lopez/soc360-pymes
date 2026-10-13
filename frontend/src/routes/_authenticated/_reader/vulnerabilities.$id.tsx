import { createFileRoute } from "@tanstack/react-router";
import { VulnerabilityDetailRoute } from "@/features/vulnerabilities";

export const Route = createFileRoute("/_authenticated/_reader/vulnerabilities/$id")({
  component: VulnerabilityDetailRoute,
});
