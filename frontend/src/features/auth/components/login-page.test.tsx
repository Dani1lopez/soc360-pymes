import { renderWithRouter } from "@/test/render";
import { LoginPage } from "./login-page";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { __resetSession } from "@/api/session";
import { makeUser, sampleCredentials, tokenBody } from "@/test/fixtures/auth";
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
  return renderWithRouter(<LoginPage />, { initialPath: "/login?redirect=/forbidden" });
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
test("blocks the button while the retry delay runs", async () => {
  server.use(
    http.post("*/api/v1/auth/login", () =>
      HttpResponse.json({}, { status: 429, headers: { "Retry-After": "30" } }),
    ),
  );
  mount();
  await submit();

  expect(await screen.findByRole("button", { name: "Espera 30 s" })).toBeDisabled();
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
test("shows unauthorized feedback without leaving login", async () => {
  server.use(
    http.post("*/api/v1/auth/login", () =>
      HttpResponse.json({ detail: "Credenciales incorrectas" }, { status: 401 }),
    ),
  );
  mount();
  await submit();
  expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales incorrectas");
});
