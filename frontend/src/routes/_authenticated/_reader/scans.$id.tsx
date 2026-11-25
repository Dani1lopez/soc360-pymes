import { createFileRoute } from "@tanstack/react-router";
import { ScanDetailRoute } from "@/features/scans";

export const Route = createFileRoute("/_authenticated/_reader/scans/$id")({
  component: ScanDetailRoute,
});
