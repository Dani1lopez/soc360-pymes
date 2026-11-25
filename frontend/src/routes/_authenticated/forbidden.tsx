import { createFileRoute } from "@tanstack/react-router";
import { ForbiddenPage } from "@/features/auth";

export const Route = createFileRoute("/_authenticated/forbidden")({ component: ForbiddenPage });
