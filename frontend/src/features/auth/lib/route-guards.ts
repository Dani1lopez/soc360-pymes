import type { QueryClient } from "@tanstack/react-query";
import { redirect } from "@tanstack/react-router";
import { restoreSession } from "@/api/session";
import { sanitizeRedirect } from "./guards";
import { currentUserQueryOptions } from "../hooks/use-current-user";

export function validateLoginSearch(search: Record<string, unknown>): { redirect?: string } {
  return search.redirect === undefined ? {} : { redirect: sanitizeRedirect(search.redirect) };
}

export async function redirectIfAuthenticated(search: { redirect?: string }) {
  if ((await restoreSession()) !== null)
    throw redirect({ href: sanitizeRedirect(search.redirect) });
}

export async function requireSession({
  context,
  location,
}: {
  context: { queryClient: QueryClient };
  location: { href: string };
}) {
  if ((await restoreSession()) === null)
    throw redirect({ to: "/login", search: { redirect: location.href } });
  const user = await context.queryClient.ensureQueryData(currentUserQueryOptions());
  return { user };
}
