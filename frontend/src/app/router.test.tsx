import { act, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AppProviders } from "./providers";
import { createAppRouter } from "./router";
import { createQueryClient } from "./query-client";
import { __resetSession, SESSION_CLEARED_EVENT } from "@/api/session";
import { makeUser, tokenBody } from "@/test/fixtures/auth";
import { currentUserQueryKey } from "@/features/auth";
import { server } from "@/test/msw";

beforeEach(() => {
  __resetSession();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});
afterEach(() => {
  __resetSession();
  vi.restoreAllMocks();
});
function mount(path: string, authenticated: boolean) {
  server.use(
    http.post("*/api/v1/auth/refresh", () =>
      authenticated ? HttpResponse.json(tokenBody("t1")) : new HttpResponse(null, { status: 401 }),
    ),
    http.get("*/api/v1/users/me", () => HttpResponse.json(makeUser())),
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
  return { router, queryClient };
}
test("sends anonymous visitors to login with their destination", async () => {
  const { router } = mount("/", false);
  expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/login");
  expect(router.state.location.search).toEqual({ redirect: "/" });
});
test("renders the authenticated home", async () => {
  mount("/", true);
  expect(await screen.findByRole("heading", { name: "SOC360 PyMEs" })).toBeInTheDocument();
});
test("redirects authenticated login visitors to the requested destination", async () => {
  const { router } = mount("/login?redirect=/forbidden", true);
  expect(await screen.findByRole("heading", { name: "Acceso denegado" })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/forbidden");
});
test.each(["//evil.com", "/a/..//evil.com"])(
  "rejects the external login destination %s",
  async (destination) => {
    const { router } = mount(`/login?redirect=${encodeURIComponent(destination)}`, true);
    expect(await screen.findByRole("heading", { name: "SOC360 PyMEs" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    expect(router.state.location.href).not.toContain("evil.com");
  },
);
test("clears cached users and navigates on session loss", async () => {
  const { router, queryClient } = mount("/", true);
  await screen.findByRole("heading", { name: "SOC360 PyMEs" });
  expect(queryClient.getQueryData(currentUserQueryKey)).toBeDefined();
  __resetSession();
  server.use(http.post("*/api/v1/auth/refresh", () => new HttpResponse(null, { status: 401 })));
  act(() => window.dispatchEvent(new Event(SESSION_CLEARED_EVENT)));
  await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  expect(queryClient.getQueryData(currentUserQueryKey)).toBeUndefined();
});
