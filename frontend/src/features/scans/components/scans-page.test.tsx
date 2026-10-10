import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { ScanResponse } from "@/api/schema";
import { currentUserQueryKey } from "@/features/auth";
import { makeAsset } from "@/test/fixtures/assets";
import { makeUser } from "@/test/fixtures/auth";
import { makeScan, scanList } from "@/test/fixtures/scans";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { ScansPage } from "./scans-page";

const asset = makeAsset();

function setup(
  scans: ScanResponse[],
  {
    role = "admin" as const,
    onList,
  }: { role?: "admin" | "viewer"; onList?: (params: Record<string, string>) => void } = {},
) {
  server.use(
    http.get("*/api/v1/assets/", () =>
      HttpResponse.json({ items: [asset], total: 1, limit: 200, offset: 0 }),
    ),
    http.get("*/api/v1/scans/", ({ request }) => {
      const params = Object.fromEntries(new URL(request.url).searchParams);
      onList?.(params);
      return HttpResponse.json(scanList(scans, { offset: Number(params.offset ?? 0) }));
    }),
  );
  return renderShell(<ScansPage />, currentUserQueryKey, makeUser({ role }));
}

describe("ScansPage", () => {
  it("lists scans with the asset value and the status label", async () => {
    setup([
      makeScan(),
      makeScan({ id: "2", name: "Descubrimiento VPN", status: "running", asset_id: asset.id }),
    ]);

    expect(await screen.findByText("Descubrimiento de la red interna")).toBeInTheDocument();
    expect(screen.getByText("Descubrimiento VPN")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getAllByText(asset.value)).toHaveLength(2);
    expect(screen.getByText("Completado")).toBeInTheDocument();
    expect(screen.getByText("En ejecución")).toBeInTheDocument();
  });

  it("shows an empty state when there are no scans", async () => {
    setup([]);
    expect(await screen.findByText("No hay escaneos")).toBeInTheDocument();
  });

  it("offers run and cancel only while the scan is open", async () => {
    setup([
      makeScan({ id: "1", name: "Escaneo pendiente", status: "pending" }),
      makeScan({ id: "2", name: "Escaneo en curso", status: "running" }),
      makeScan({ id: "3", name: "Escaneo terminado", status: "completed" }),
    ]);

    await screen.findByRole("link", { name: "Escaneo pendiente" });
    const rows = screen.getAllByRole("row").slice(1);

    expect(rows[0]!).toHaveTextContent("Ejecutar");
    expect(rows[0]!).toHaveTextContent("Cancelar");
    expect(rows[1]!).not.toHaveTextContent("Ejecutar");
    expect(rows[1]!).toHaveTextContent("Cancelar");
    expect(rows[2]!).not.toHaveTextContent("Ejecutar");
    expect(rows[2]!).not.toHaveTextContent("Cancelar");
  });

  it("hides every write action from a viewer", async () => {
    setup([makeScan({ status: "pending" })], { role: "viewer" });

    await screen.findByText("Descubrimiento de la red interna");
    expect(screen.queryByRole("button", { name: /Nuevo escaneo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ejecutar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Eliminar" })).not.toBeInTheDocument();
  });

  it("dispatches a pending scan", async () => {
    setup([makeScan({ status: "pending" })]);
    const run = vi.fn();
    server.use(
      http.post("*/api/v1/scans/:id/run", ({ params }) => {
        run(params.id);
        return HttpResponse.json(makeScan({ status: "pending" }), { status: 202 });
      }),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: /Ejecutar/ }));

    await waitFor(() => expect(run).toHaveBeenCalledWith(makeScan().id));
  });

  it("cancels a running scan", async () => {
    setup([makeScan({ status: "running" })]);
    const cancel = vi.fn();
    server.use(
      http.post("*/api/v1/scans/:id/cancel", ({ params }) => {
        cancel(params.id);
        return HttpResponse.json(makeScan({ status: "cancelled" }));
      }),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: /Cancelar/ }));

    await waitFor(() => expect(cancel).toHaveBeenCalledWith(makeScan().id));
  });

  it("surfaces the backend refusal as an alert", async () => {
    setup([makeScan({ status: "pending" })]);
    server.use(
      http.post("*/api/v1/scans/:id/run", () =>
        HttpResponse.json({ detail: "scan execution is disabled" }, { status: 403 }),
      ),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: /Ejecutar/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("scan execution is disabled");
  });

  it("creates a scan with the selected asset", async () => {
    setup([makeScan()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/scans/", async ({ request }) => {
        posted(await request.json());
        return HttpResponse.json(makeScan({ status: "pending" }), { status: 201 });
      }),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: /Nuevo escaneo/ }));
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Auditoría web" } });
    fireEvent.change(screen.getByLabelText("Activo"), { target: { value: asset.id } });
    fireEvent.change(screen.getByLabelText("Tipo"), { target: { value: "web" } });
    fireEvent.change(screen.getByLabelText("Rutas"), { target: { value: "/, /login" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear escaneo" }));

    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith({
        asset_id: asset.id,
        name: "Auditoría web",
        tenant_id: makeUser().tenant_id,
        type: "web",
        config: { paths: ["/", "/login"] },
      }),
    );
  });

  it("refuses an incomplete form without calling the API", async () => {
    setup([makeScan()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/scans/", () => {
        posted();
        return HttpResponse.json(makeScan(), { status: 201 });
      }),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: /Nuevo escaneo/ }));
    fireEvent.click(screen.getByRole("button", { name: "Crear escaneo" }));

    expect(await screen.findByText("Introduce un nombre.")).toBeInTheDocument();
    expect(screen.getByText("Selecciona un activo.")).toBeInTheDocument();
    expect(posted).not.toHaveBeenCalled();
  });

  it("filters by asset and resets the page", async () => {
    const requests: Record<string, string>[] = [];
    setup([makeScan()], { onList: (params) => requests.push(params) });

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.change(screen.getByLabelText("Filtrar por activo"), { target: { value: asset.id } });

    await waitFor(() =>
      expect(requests.some((params) => params.asset_id === asset.id && params.offset === "0")).toBe(
        true,
      ),
    );
  });

  it("deletes a scan after confirming", async () => {
    setup([makeScan()]);
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/scans/:id", ({ params }) => {
        deleted(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await screen.findByText("Descubrimiento de la red interna");
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(deleted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Eliminar escaneo" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith(makeScan().id));
  });
});
