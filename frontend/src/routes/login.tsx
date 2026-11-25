import { createFileRoute } from "@tanstack/react-router";
import { LoginPage, validateLoginSearch, redirectIfAuthenticated } from "@/features/auth";

export const Route = createFileRoute("/login")({
  validateSearch: validateLoginSearch,
  beforeLoad: ({ search }) => redirectIfAuthenticated(search),
  component: LoginPage,
});
