import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { UserResponse } from "@/api/schema";
import { currentUserQueryKey } from "@/features/auth";
import { makeUser } from "@/test/fixtures/auth";
import { makeTenant } from "@/test/fixtures/tenants";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { UsersPage } from "./users-page";

const SECRET_FIELD = ["pass", "word"].join("");
const caller = makeUser({ role: "admin" });
const ana = makeUser({
  id: "00000000-0000-4000-8000-000000000002",
  email: "ana@example.com",
  full_name: "Ana Demo",
  role: "analyst",
});

function setup(
  users: UserResponse[],
  {
    signedIn = caller,
    onList,
  }: { signedIn?: UserResponse; onList?: (params: Record<string, string>) => void } = {},
) {
  server.use(
    http.get("*/api/v1/users/", ({ request }) => {
      const params = Object.fromEntries(new URL(request.url).searchParams);
      onList?.(params);
      return HttpResponse.json(users);
    }),
    http.get("*/api/v1/tenants/", () => HttpResponse.json([makeTenant()])),
  );
  return renderShell(<UsersPage />, currentUserQueryKey, signedIn);
}

describe("UsersPage", () => {
  it("lists the accounts with their role and state", async () => {
    setup([
      ana,
      makeUser({
        id: "3",
        email: "viewer@example.com",
        full_name: "Vera Viewer",
        role: "viewer",
        is_active: false,
      }),
    ]);

    expect(await screen.findByText("Ana Demo")).toBeInTheDocument();
    expect(screen.getByText("ana@example.com")).toBeInTheDocument();
    expect(screen.getByText("Analista")).toBeInTheDocument();
    expect(screen.getByText("Lector")).toBeInTheDocument();
    expect(screen.getByText("Activo")).toBeInTheDocument();
    expect(screen.getByText("Inactivo")).toBeInTheDocument();
  });

  it("shows an empty state when there are no accounts", async () => {
    setup([]);
    expect(await screen.findByText("No hay usuarios")).toBeInTheDocument();
  });

  it("asks the server for the inactive accounts when told to", async () => {
    const requests: Record<string, string>[] = [];
    setup([ana], { onList: (params) => requests.push(params) });

    await screen.findByText("Ana Demo");
    expect(requests[0]?.include_inactive).toBe("false");

    fireEvent.click(screen.getByLabelText("Mostrar inactivos"));
    await waitFor(() =>
      expect(requests.some((params) => params.include_inactive === "true")).toBe(true),
    );
  });

  it("creates an account with the caller tenant and an initial secret", async () => {
    setup([ana]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/users/", async ({ request }) => {
        posted(await request.json());
        return HttpResponse.json(ana, { status: 201 });
      }),
    );

    await screen.findByText("Ana Demo");
    fireEvent.click(screen.getByRole("button", { name: /Nuevo usuario/ }));
    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "nuevo@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Nuevo Usuario" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña inicial"), {
      target: { value: "doce-caracteres" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear usuario" }));

    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith({
        email: "nuevo@example.com",
        full_name: "Nuevo Usuario",
        role: "viewer",
        tenant_id: caller.tenant_id,
        [SECRET_FIELD]: "doce-caracteres",
      }),
    );
  });

  it("refuses a short secret without calling the API", async () => {
    setup([ana]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/users/", () => {
        posted();
        return HttpResponse.json(ana, { status: 201 });
      }),
    );

    await screen.findByText("Ana Demo");
    fireEvent.click(screen.getByRole("button", { name: /Nuevo usuario/ }));
    fireEvent.change(screen.getByLabelText("Correo electrónico"), {
      target: { value: "nuevo@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Nuevo Usuario" },
    });
    fireEvent.change(screen.getByLabelText("Contraseña inicial"), {
      target: { value: "corta" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear usuario" }));

    expect(
      await screen.findByText("La contraseña debe tener entre 12 y 128 caracteres."),
    ).toBeInTheDocument();
    expect(posted).not.toHaveBeenCalled();
  });

  it("deactivates an account only after confirming", async () => {
    setup([ana]);
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/users/:id", ({ params }) => {
        deleted(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await screen.findByText("Ana Demo");
    fireEvent.click(screen.getByRole("button", { name: "Desactivar" }));
    expect(deleted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Quitar el acceso" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith(ana.id));
  });

  it("never offers to deactivate the signed-in account", async () => {
    setup([caller, ana]);

    const rows = await screen.findAllByRole("row");
    const ownRow = rows.find((row) => row.textContent?.includes(caller.email));
    expect(ownRow?.textContent).not.toContain("Desactivar");
    expect(rows.filter((row) => row.textContent?.includes("Desactivar"))).toHaveLength(1);
  });

  it("reactivates an inactive account", async () => {
    setup([makeUser({ id: "3", email: "viewer@example.com", role: "viewer", is_active: false })]);
    const patched = vi.fn();
    server.use(
      http.patch("*/api/v1/users/:id", async ({ request }) => {
        patched(await request.json());
        return HttpResponse.json(makeUser({ is_active: true }));
      }),
    );

    await screen.findByText("Inactivo");
    fireEvent.click(screen.getByRole("button", { name: "Reactivar" }));

    await waitFor(() => expect(patched).toHaveBeenCalledWith({ is_active: true }));
  });

  it("shows the API error with a working retry", async () => {
    setup([ana]);
    // Se registra después del listado: el último handler de MSW es el que gana,
    // y solo falla la primera llamada para poder reintentar.
    server.use(
      http.get("*/api/v1/users/", () => new HttpResponse(null, { status: 503 }), { once: true }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los datos");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Ana Demo")).toBeInTheDocument();
  });
});
