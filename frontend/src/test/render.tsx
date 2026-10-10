import type { ReactElement } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  RouterProvider,
} from "@tanstack/react-router";

export function renderShell(ui: ReactElement, queryKey: readonly unknown[], user: unknown) {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(queryKey, user);
  const root = createRootRoute({ component: () => ui });
  const paths = ["/", "/assets", "/scans", "/vulnerabilities", "/reports", "/users", "/settings"];
  const routes = paths.map((path) =>
    createRoute({ getParentRoute: () => root, path, component: () => <h1>Content</h1> }),
  );
  const router = createRouter({
    routeTree: root.addChildren(routes),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  return { router, ...renderWithQueryClient(<RouterProvider router={router} />, queryClient) };
}

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

export function renderWithQueryClient(ui: ReactElement, queryClient = createTestQueryClient()) {
  return {
    queryClient,
    ...render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>),
  };
}

export function renderWithRouter(
  ui: ReactElement,
  {
    initialPath = "/login",
    target = <h1>Acceso denegado</h1>,
  }: { initialPath?: string; target?: ReactElement } = {},
) {
  const root = createRootRoute({ component: Outlet });
  const login = createRoute({
    getParentRoute: () => root,
    path: "/login",
    validateSearch: (search: Record<string, unknown>) => ({
      redirect: typeof search.redirect === "string" ? search.redirect : undefined,
    }),
    component: () => ui,
  });
  const destination = createRoute({
    getParentRoute: () => root,
    path: "/forbidden",
    component: () => target,
  });
  const router = createRouter({
    routeTree: root.addChildren([login, destination]),
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
  return { router, ...renderWithQueryClient(<RouterProvider router={router} />) };
}
