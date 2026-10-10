import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  redirect,
  type RouterHistory,
} from "@tanstack/react-router";
import type { QueryClient } from "@tanstack/react-query";
import App from "@/App";
import { restoreSession } from "@/api/session";
import { sanitizeRedirect } from "@/features/auth/guards";
import { LoginPage } from "@/features/auth/login-page";
import { SessionWatcher } from "@/features/auth/session-watcher";
import { currentUserQueryOptions } from "@/features/auth/use-current-user";
import { ForbiddenPage } from "./forbidden-page";

export const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: () => (
    <>
      <SessionWatcher />
      <Outlet />
    </>
  ),
});
export const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  validateSearch: (search: Record<string, unknown>): { redirect?: string } =>
    search.redirect === undefined ? {} : { redirect: sanitizeRedirect(search.redirect) },
  beforeLoad: async ({ search }) => {
    if ((await restoreSession()) !== null)
      throw redirect({ href: sanitizeRedirect(search.redirect) });
  },
  component: LoginPage,
});
export const authenticatedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authenticated",
  beforeLoad: async ({ context, location }) => {
    if ((await restoreSession()) === null)
      throw redirect({ to: "/login", search: { redirect: location.href } });
    const user = await context.queryClient.ensureQueryData(currentUserQueryOptions());
    return { user };
  },
  component: Outlet,
});
export const indexRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/",
  component: App,
});
export const forbiddenRoute = createRoute({
  getParentRoute: () => authenticatedRoute,
  path: "/forbidden",
  component: ForbiddenPage,
});
export const routeTree = rootRoute.addChildren([
  loginRoute,
  authenticatedRoute.addChildren([indexRoute, forbiddenRoute]),
]);

export function createAppRouter({
  queryClient,
  history,
}: {
  queryClient: QueryClient;
  history?: RouterHistory;
}) {
  return createRouter({ routeTree, history, context: { queryClient } });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
