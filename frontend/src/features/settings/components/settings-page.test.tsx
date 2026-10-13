import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { getBearer, setBearer } from "@/api/session";
import { currentUserQueryKey } from "@/features/auth";
import { makeUser } from "@/test/fixtures/auth";
import { makeTenant } from "@/test/fixtures/tenants";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { SettingsPage } from "./settings-page";

function setup(superadmin = false) {
  const tenant = makeTenant();
  const listed = vi.fn();
  server.use(
    http.get("*/api/v1/tenants/:id", () => HttpResponse.json(tenant)),
    http.get("*/api/v1/tenants/", () => {
      listed();
      return HttpResponse.json([tenant, makeTenant({ id: "second", name: "Otra organización" })]);
    }),
  );
  return {
    listed,
    ...renderShell(
      <SettingsPage />,
      currentUserQueryKey,
      makeUser({
        role: superadmin ? "superadmin" : "admin",
        is_superadmin: superadmin,
        tenant_id: tenant.id,
      }),
    ),
  };
}

function fillPassword() {
  fireEvent.change(screen.getByLabelText("Contraseña actual"), {
    target: { value: "old-sample-value" },
  });
  fireEvent.change(screen.getByLabelText("Nueva contraseña"), {
    target: { value: "new-sample-value" },
  });
  fireEvent.change(screen.getByLabelText("Repetir nueva contraseña"), {
    target: { value: "new-sample-value" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
}

describe("SettingsPage", () => {
  it("shows read-only organization settings for admin without listing tenants", async () => {
    const { listed } = setup();
    expect(await screen.findByLabelText("Nombre")).toHaveValue("Acme Corp");
    expect(screen.getByLabelText("Nombre")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Plan")).toBeDisabled();
    expect(
      screen.getByText(
        "Solo un superadministrador puede modificar la configuración de la organización",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar configuración" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña actual")).toBeInTheDocument();
    expect(listed).not.toHaveBeenCalled();
  });
  it("patches organization settings for superadmin while preserving hidden values", async () => {
    setup(true);
    const seen = vi.fn();
    server.use(
      http.patch("*/api/v1/tenants/:id", async ({ params, request }) => {
        seen(params.id, await request.json());
        return HttpResponse.json(makeTenant({ name: "Nuevo nombre" }));
      }),
    );
    await screen.findByLabelText("Nombre");
    expect(screen.getByLabelText("Organización")).toHaveValue(makeTenant().id);
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Nuevo nombre" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar configuración" }));
    await waitFor(() =>
      expect(seen).toHaveBeenCalledWith(
        makeTenant().id,
        expect.objectContaining({ name: "Nuevo nombre", settings: makeTenant().settings }),
      ),
    );
    expect(await screen.findByText("Configuración guardada.")).toBeInTheDocument();
  });
  it("changes the selected organization without retaining the previous draft", async () => {
    setup(true);
    server.use(
      http.get("*/api/v1/tenants/:id", ({ params }) =>
        HttpResponse.json(
          makeTenant({
            id: String(params.id),
            name: params.id === "second" ? "Otra organización" : "Acme Corp",
          }),
        ),
      ),
    );
    await screen.findByLabelText("Nombre");
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Borrador" } });
    fireEvent.change(screen.getByLabelText("Organización"), { target: { value: "second" } });
    await waitFor(() => expect(screen.getByLabelText("Nombre")).toHaveValue("Otra organización"));
  });
  it("clears the local session and navigates to login on successful change", async () => {
    const { router } = setup();
    setBearer("session-sample-value");
    server.use(
      http.post("*/api/v1/auth/change-password", () => HttpResponse.json({ detail: "ok" })),
    );
    await screen.findByLabelText("Nombre");
    fillPassword();
    await waitFor(() => {
      expect(getBearer()).toBeNull();
      expect(router.state.location.pathname).toBe("/login");
    });
  });
  it("keeps the session and shows an error when rate limited", async () => {
    const { router } = setup();
    setBearer("session-sample-value");
    server.use(
      http.post("*/api/v1/auth/change-password", () =>
        HttpResponse.json({ detail: "Demasiados intentos" }, { status: 429 }),
      ),
    );
    await screen.findByLabelText("Nombre");
    fillPassword();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(getBearer()).not.toBeNull();
    expect(router.state.location.pathname).not.toBe("/login");
  });
  it("validates before sending and links Spanish errors to controls", async () => {
    setup();
    const called = vi.fn();
    server.use(
      http.post("*/api/v1/auth/change-password", () => {
        called();
        return HttpResponse.json({ detail: "ok" });
      }),
    );
    await screen.findByLabelText("Nombre");
    fireEvent.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
    expect(screen.getByLabelText("Contraseña actual")).toHaveAttribute(
      "aria-describedby",
      "settings-current-error",
    );
    expect(screen.getByText("Introduce la contraseña actual.")).toBeInTheDocument();
    expect(called).not.toHaveBeenCalled();
  });
});
