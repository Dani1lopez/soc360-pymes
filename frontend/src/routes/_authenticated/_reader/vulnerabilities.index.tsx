import { createFileRoute } from "@tanstack/react-router";
import { VulnerabilitiesPage } from "@/features/vulnerabilities";

export const Route = createFileRoute("/_authenticated/_reader/vulnerabilities/")({
  component: VulnerabilitiesPage,
});
