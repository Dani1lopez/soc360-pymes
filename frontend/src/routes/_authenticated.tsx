import { createFileRoute } from "@tanstack/react-router";
import { requireSession, SessionErrorPage } from "@/features/auth";
import { AppShell } from "@/features/shell";

export const Route = createFileRoute("/_authenticated")({
  beforeLoad: requireSession,
  component: AppShell,
  errorComponent: SessionErrorPage,
});
