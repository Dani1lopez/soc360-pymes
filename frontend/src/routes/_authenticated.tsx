import { createFileRoute, Outlet } from "@tanstack/react-router";
import { requireSession } from "@/features/auth";

export const Route = createFileRoute("/_authenticated")({
  beforeLoad: requireSession,
  component: Outlet,
});
