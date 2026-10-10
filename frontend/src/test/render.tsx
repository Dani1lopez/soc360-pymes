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
