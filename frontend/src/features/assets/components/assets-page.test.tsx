import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssetResponse } from "@/api/schema";
import type { Role } from "@/api/schema";
import { makeUser } from "@/test/fixtures/auth";
import { assetList, makeAsset } from "@/test/fixtures/assets";
import { server } from "@/test/msw";
import { renderWithQueryClient } from "@/test/render";
import { AssetsPage } from "./assets-page";

type ListRequest = { offset: string | null; limit: string | null };

function useList(
  assets: AssetResponse[],
  {
    total = assets.length,
    onRequest,
  }: { total?: number; onRequest?: (params: ListRequest) => void } = {},
) {
  server.use(
    http.get("*/api/v1/assets/", ({ request }) => {
      const params = new URL(request.url).searchParams;
      onRequest?.({ offset: params.get("offset"), limit: params.get("limit") });
      const offset = Number(params.get("offset") ?? 0);
      return HttpResponse.json(assetList(assets, { total, offset }));
    }),
  );
}

function useUser(role: Role = "admin") {
  server.use(http.get("*/api/v1/users/me", () => HttpResponse.json(makeUser({ role }))));
}

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AssetsPage", () => {
  it("lists the assets with a readable type label", async () => {
    useUser();
    useList([makeAsset(), makeAsset({ id: "2", type: "ip", value: "192.0.2.10" })]);

    renderWithQueryClient(<AssetsPage />);

    expect(await screen.findByText("acme-corp.example")).toBeInTheDocument();
    expect(screen.getByText("Dominio")).toBeInTheDocument();
    expect(screen.getByText("192.0.2.10")).toBeInTheDocument();
    expect(screen.getByText("Dirección IP")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1–2 de 2")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing to list", async () => {
    useUser();
    useList([]);

    renderWithQueryClient(<AssetsPage />);

    expect(await screen.findByText("No hay activos")).toBeInTheDocument();
    expect(screen.getByText(/Añade un dominio/)).toBeInTheDocument();
  });

  it("shows the API error with a working retry", async () => {
    useUser();
    useList([makeAsset()]);
    // Se registra después del listado: el último handler de MSW es el que gana,
    // y solo falla la primera llamada para poder reintentar.
    server.use(
      http.get("*/api/v1/assets/", () => new HttpResponse(null, { status: 503 }), { once: true }),
    );

    renderWithQueryClient(<AssetsPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los datos");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("acme-corp.example")).toBeInTheDocument();
  });

  it("hides write actions from a viewer", async () => {
    useUser("viewer");
    useList([makeAsset()]);

    renderWithQueryClient(<AssetsPage />);

    await screen.findByText("acme-corp.example");
    expect(screen.queryByRole("button", { name: /Nuevo activo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Eliminar" })).not.toBeInTheDocument();
  });

  it("warns an admin without a tenant instead of offering a broken form", async () => {
    server.use(
      http.get("*/api/v1/users/me", () =>
        HttpResponse.json(makeUser({ role: "superadmin", tenant_id: null, is_superadmin: true })),
      ),
    );
    useList([makeAsset()]);

    renderWithQueryClient(<AssetsPage />);

    expect(
      await screen.findByText(/necesitas una cuenta asociada a una organización/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Nuevo activo/ })).not.toBeInTheDocument();
  });

  it("creates an asset with the signed-in tenant and closes the form", async () => {
    useUser();
    useList([makeAsset()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/assets/", async ({ request }) => {
        posted(await request.json());
        return HttpResponse.json(makeAsset({ id: "nuevo" }), { status: 201 });
      }),
    );

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    fireEvent.click(screen.getByRole("button", { name: /Nuevo activo/ }));
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "web_app" } });
    fireEvent.change(screen.getByLabelText("Valor"), {
      target: { value: "https://app.acme-corp.example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear activo" }));

    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith({
        tenant_id: makeUser().tenant_id,
        type: "web_app",
        value: "https://app.acme-corp.example",
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Nuevo activo" })).not.toBeInTheDocument(),
    );
  });

  it("validates the pair type/value before calling the API", async () => {
    useUser();
    useList([makeAsset()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/assets/", () => {
        posted();
        return HttpResponse.json(makeAsset(), { status: 201 });
      }),
    );

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    fireEvent.click(screen.getByRole("button", { name: /Nuevo activo/ }));
    fireEvent.change(screen.getByLabelText("Valor"), { target: { value: "no-es-una-ip" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear activo" }));

    expect(await screen.findByText(/no es válido para el tipo/)).toBeInTheDocument();
    expect(screen.getByLabelText("Valor")).toHaveAttribute("aria-invalid", "true");
    expect(posted).not.toHaveBeenCalled();
  });

  it("edits an asset", async () => {
    useUser();
    useList([makeAsset()]);
    const patched = vi.fn();
    server.use(
      http.patch("*/api/v1/assets/:id", async ({ request }) => {
        patched(await request.json());
        return HttpResponse.json(makeAsset({ value: "nuevo.example" }));
      }),
    );

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    fireEvent.click(screen.getByRole("button", { name: "Editar" }));
    expect(screen.getByRole("heading", { name: "Editar activo" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Valor"), { target: { value: "nuevo.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar cambios" }));

    await waitFor(() =>
      expect(patched).toHaveBeenCalledWith({ type: "domain", value: "nuevo.example" }),
    );
  });

  it("deletes an asset only after confirming", async () => {
    useUser();
    useList([makeAsset()]);
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/assets/:id", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(deleted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Dar de baja" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });

  it("requests the next page with an offset", async () => {
    useUser();
    const offsets: (string | null)[] = [];
    useList([makeAsset({ id: "1" })], {
      total: 30,
      onRequest: ({ offset }) => offsets.push(offset),
    });

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    expect(offsets).toEqual(["0"]);
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

    await waitFor(() => expect(offsets).toContain("20"));
  });

  it("downloads the CSV export", async () => {
    useUser();
    server.use(
      http.get("*/api/v1/assets/", ({ request }) => {
        if (new URL(request.url).searchParams.get("export") === "csv") {
          return new HttpResponse("id,type\n1,domain", { headers: { "Content-Type": "text/csv" } });
        }
        return HttpResponse.json(assetList([makeAsset()]));
      }),
    );
    const createObjectURL = vi.fn(() => "blob:activos");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, "createObjectURL", { writable: true, value: createObjectURL });
    Object.defineProperty(URL, "revokeObjectURL", { writable: true, value: revokeObjectURL });

    renderWithQueryClient(<AssetsPage />);
    await screen.findByText("acme-corp.example");

    fireEvent.click(screen.getByRole("button", { name: /Exportar CSV/ }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledTimes(1));
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });
});
