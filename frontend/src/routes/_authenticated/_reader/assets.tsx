import { createFileRoute } from "@tanstack/react-router";
import { AssetsPage } from "@/features/assets";

export const Route = createFileRoute("/_authenticated/_reader/assets")({
  component: AssetsPage,
});
