import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { currentUserQueryKey } from "@/features/auth";
import { makeAsset } from "@/test/fixtures/assets";
import { makeUser } from "@/test/fixtures/auth";
import { makeScan } from "@/test/fixtures/scans";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { ScanDetailPage } from "./scan-detail-page";

const asset = makeAsset();

function setup(scan = makeScan()) {
  server.use(
    http.get("*/api/v1/assets/", () =>
      HttpResponse.json({ items: [asset], total: 1, limit: 200, offset: 0 }),
    ),
    http.get("*/api/v1/scans/:id", () => HttpResponse.json(scan)),
  );
  return renderShell(
    <ScanDetailPage scanId={scan.id} />,
    currentUserQueryKey,
    makeUser({ role: "admin" }),
  );
}

describe("ScanDetailPage", () => {
  it("shows the scan, its asset and its configuration", async () => {
    setup();

    expect(await screen.findByRole("heading", { name: makeScan().name })).toBeInTheDocument();
    expect(screen.getByText(asset.value)).toBeInTheDocument();
    expect(screen.getByText("Descubrimiento")).toBeInTheDocument();
    expect(screen.getByText("host_discovery: true")).toBeInTheDocument();
    expect(screen.getByText("Completado")).toBeInTheDocument();
  });

  it("runs a pending scan and refreshes it", async () => {
    setup(makeScan({ status: "pending" }));
    const run = vi.fn();
    server.use(
      http.post("*/api/v1/scans/:id/run", () => {
        run();
        return HttpResponse.json(makeScan({ status: "pending" }), { status: 202 });
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: /Ejecutar/ }));

    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
  });

  it("deletes the scan after confirming", async () => {
    setup(makeScan({ status: "completed" }));
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/scans/:id", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await screen.findByRole("heading", { name: makeScan().name });
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    fireEvent.click(screen.getByRole("button", { name: "Eliminar escaneo" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
  });

  it("explains a missing scan and offers retry", async () => {
    server.use(
      http.get("*/api/v1/assets/", () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
      http.get("*/api/v1/scans/:id", () =>
        HttpResponse.json({ detail: "scan not found" }, { status: 404 }),
      ),
    );
    renderShell(
      <ScanDetailPage scanId="missing" />,
      currentUserQueryKey,
      makeUser({ role: "admin" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("scan not found");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
