import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { currentUserQueryKey } from "@/features/auth";
import { makeUser } from "@/test/fixtures/auth";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { AppShell } from "./app-shell";

beforeEach(() => vi.spyOn(window, "scrollTo").mockImplementation(() => {}));
afterEach(() => vi.restoreAllMocks());

test.each([
  ["viewer", "Lector", 6],
  ["analyst", "Analista", 6],
  ["admin", "Administrador", 7],
  ["superadmin", "Superadministrador", 7],
] as const)("renders %s navigation and identity", async (role, label, count) => {
  renderShell(<AppShell />, currentUserQueryKey, makeUser({ role }));
  const nav = await screen.findByRole("navigation", { name: "Navegación principal" });
  expect(within(nav).getByRole("link", { name: "Configuración" })).toHaveAttribute(
    "href",
    "/settings",
  );
  expect(within(nav).getAllByRole("link")).toHaveLength(count);
  expect(
    within(screen.getByRole("banner")).getByRole("button", { name: /^Tema:/ }),
  ).toBeInTheDocument();
  expect(screen.getByText("Ana Demo")).toBeInTheDocument();
  expect(screen.getByText(label)).toBeInTheDocument();
  if (role === "viewer" || role === "analyst") {
    expect(within(nav).queryByText("Usuarios")).not.toBeInTheDocument();
  } else {
    expect(within(nav).getByText("Usuarios")).toBeInTheDocument();
  }
  expect(within(nav).getByRole("link", { name: "Panel" })).toHaveAttribute("aria-current", "page");
});
test("posts logout and toggles the mobile menu", async () => {
  const logout = vi.fn(() => new HttpResponse(null, { status: 204 }));
  server.use(http.post("*/api/v1/auth/logout", logout));
  renderShell(<AppShell />, currentUserQueryKey, makeUser());
  const menu = await screen.findByRole("button", { name: "Menú" });
  expect(menu).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(menu);
  expect(menu).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  await waitFor(() => expect(logout).toHaveBeenCalledOnce());
});
