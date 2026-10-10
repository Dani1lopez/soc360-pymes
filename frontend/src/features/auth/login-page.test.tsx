import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { AppProviders } from "@/app/providers";
import { createAppRouter } from "@/app/router";
import { createQueryClient } from "@/app/query-client";
import { __resetSession } from "@/api/session";
import { makeUser, sampleCredentials, tokenBody } from "./test-fixtures";
import { currentUserQueryKey } from "./use-current-user";
import { server } from "@/test/msw";

beforeEach(() => {
  __resetSession();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  server.use(
    http.post("*/api/v1/auth/refresh", () => new HttpResponse(null, { status: 401 })),
    http.get("*/api/v1/users/me", () => HttpResponse.json(makeUser())),
  );
});
afterEach(() => {
  __resetSession();
  vi.restoreAllMocks();
});
function mount() {
  const queryClient = createQueryClient();
  const router = createAppRouter({
    queryClient,
    history: createMemoryHistory({ initialEntries: ["/login?redirect=/forbidden"] }),
  });
  render(
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
  return { router, queryClient };
}
async function submit() {
  const creds = sampleCredentials();
  const { email, password } = creds;
  fireEvent.change(await screen.findByLabelText("Correo electrónico"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Contraseña"), { target: { value: password } });
  fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
}
test("caches the user before navigating to the requested destination", async () => {
  server.use(http.post("*/api/v1/auth/login", () => HttpResponse.json(tokenBody("login-session"))));
  const { router, queryClient } = mount();
  await submit();
  await screen.findByRole("heading", { name: "Acceso denegado" });
  expect(router.state.location.pathname).toBe("/forbidden");
  expect(queryClient.getQueryData(currentUserQueryKey)).toEqual(makeUser());
});
test("leaves login without re-authenticating when the user lookup fails", async () => {
  const loginHandler = vi.fn(() => HttpResponse.json(tokenBody("login-session")));
  server.use(
    http.post("*/api/v1/auth/login", loginHandler),
    http.get("*/api/v1/users/me", () => new HttpResponse(null, { status: 500 })),
  );
  const { router, queryClient } = mount();
  queryClient.setQueryDefaults(currentUserQueryKey, { retry: false });
  await submit();
  await waitFor(() => expect(router.state.location.pathname).not.toBe("/login"));
  expect(loginHandler).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
test("shows unauthorized feedback without leaving login", async () => {
  server.use(
    http.post("*/api/v1/auth/login", () =>
      HttpResponse.json({ detail: "Credenciales incorrectas" }, { status: 401 }),
    ),
  );
  const { router } = mount();
  await submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales incorrectas");
  expect(router.state.location.pathname).toBe("/login");
});
test("links validation feedback to the invalid field", async () => {
  server.use(
    http.post("*/api/v1/auth/login", () =>
      HttpResponse.json(
        { detail: [{ type: "missing", loc: ["body", "email"], msg: "Field required" }] },
        { status: 422 },
      ),
    ),
  );
  mount();
  await submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Revisa los campos del formulario.");
  expect(screen.getByLabelText("Correo electrónico")).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByLabelText("Correo electrónico")).toHaveAccessibleDescription(
    "Campo obligatorio",
  );
});
test("shows the retry delay", async () => {
  server.use(
    http.post("*/api/v1/auth/login", () =>
      HttpResponse.json({}, { status: 429, headers: { "Retry-After": "30" } }),
    ),
  );
  mount();
  await submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Demasiados intentos. Vuelve a intentarlo en 30 s.",
  );
});
test("disables submission while pending", async () => {
  let finish: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  server.use(
    http.post("*/api/v1/auth/login", async () => {
      await pending;
      return HttpResponse.json(tokenBody("pending-session"));
    }),
  );
  mount();
  await submit();
  await waitFor(() => expect(screen.getByRole("button", { name: "Entrando…" })).toBeDisabled());
  finish?.();
  await screen.findByRole("heading", { name: "Acceso denegado" });
});
