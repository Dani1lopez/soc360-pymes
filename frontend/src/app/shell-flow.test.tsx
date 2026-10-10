import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Role } from "@/api/schema";
import { __resetSession } from "@/api/session";
import { makeUser, tokenBody } from "@/test/fixtures/auth";
import { server } from "@/test/msw";
import { AppProviders } from "./providers";
import { createAppRouter } from "./router";
import { createQueryClient } from "./query-client";

beforeEach(() => {
  __resetSession();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});
afterEach(() => {
  __resetSession();
  vi.restoreAllMocks();
});
function mount(path: string, role: Role, failed = false) {
  server.use(
    http.post("*/api/v1/auth/refresh", () => HttpResponse.json(tokenBody("shell"))),
    http.get("*/api/v1/users/me", () =>
      failed ? new HttpResponse(null, { status: 500 }) : HttpResponse.json(makeUser({ role })),
    ),
  );
  const queryClient = createQueryClient();
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return router;
}
test.each([
  ["viewer", "/users"],
  ["ingestor", "/"],
] as const)("denies %s at %s", async (role, path) => {
  const router = mount(path, role);
  expect(await screen.findByRole("heading", { name: "Acceso denegado" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/forbidden");
});
test("admin can open users", async () => {
  mount("/users", "admin");
  expect(await screen.findByRole("heading", { name: "Usuarios" })).toBeInTheDocument();
});
test("shell logout ends at login", async () => {
  const logout = vi.fn(() => {
    server.use(http.post("*/api/v1/auth/refresh", () => new HttpResponse(null, { status: 401 })));
    return new HttpResponse(null, { status: 204 });
  });
  server.use(http.post("*/api/v1/auth/logout", logout));
  const router = mount("/", "viewer");
  fireEvent.click(await screen.findByRole("button", { name: "Cerrar sesión" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(logout).toHaveBeenCalledOnce();
  expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
});
test("session failure can be retried", async () => {
  mount("/", "viewer", true);
  expect(
    await screen.findByRole("heading", { name: "No se pudo cargar tu sesión" }, { timeout: 5000 }),
  ).toBeInTheDocument();
  server.use(http.get("*/api/v1/users/me", () => HttpResponse.json(makeUser({ role: "viewer" }))));
  fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
  expect(await screen.findByRole("heading", { name: "SOC360 PyMEs" })).toBeInTheDocument();
});
