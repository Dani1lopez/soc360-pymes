import { createFileRoute } from "@tanstack/react-router";
import { ScansPage } from "@/features/scans";

export const Route = createFileRoute("/_authenticated/_reader/scans/")({
  component: ScansPage,
});
