import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { ReportResponse, Role } from "@/api/schema";
import { currentUserQueryKey } from "@/features/auth";
import { formatDateTime } from "@/lib/format";
import { makeAsset, assetList } from "@/test/fixtures/assets";
import { makeUser } from "@/test/fixtures/auth";
import { makeReport, reportList } from "@/test/fixtures/reports";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { ReportsPage } from "./reports-page";

const asset = makeAsset();
function setup(items: ReportResponse[] = [makeReport()], role: Role = "admin") {
  server.use(
    http.get("*/api/v1/assets/", () => HttpResponse.json(assetList([asset]))),
    http.get("*/api/v1/reports/", () => HttpResponse.json(reportList(items))),
  );
  return renderShell(<ReportsPage />, currentUserQueryKey, makeUser({ role }));
}

describe("ReportsPage", () => {
  it("lists type, status, asset and dates with the metadata-only notice", async () => {
    const report = makeReport({ generated_at: "2026-10-03T12:00:00Z" });
    setup([report]);
    await screen.findByText(report.name);
    const table = within(screen.getByRole("table"));
    expect(await table.findByText(asset.value)).toBeInTheDocument();
    expect(table.getByText("Vulnerabilidades")).toBeInTheDocument();
    expect(table.getByText("Pendiente")).toBeInTheDocument();
    expect(table.getByText(formatDateTime(report.generated_at))).toBeInTheDocument();
    expect(table.getByText(formatDateTime(report.updated_at))).toBeInTheDocument();
    expect(screen.getByText(/La generación y la descarga de PDF/)).toBeInTheDocument();
  });
  it("shows an empty state", async () => {
    setup([]);
    expect(await screen.findByText("No hay informes")).toBeInTheDocument();
  });
  it("retries a failed API request", async () => {
    setup();
    server.use(
      http.get("*/api/v1/reports/", () =>
        HttpResponse.json({ detail: "Servicio no disponible" }, { status: 500 }),
      ),
    );
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    server.use(http.get("*/api/v1/reports/", () => HttpResponse.json(reportList([makeReport()]))));
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText(makeReport().name)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
  it("hides creation and row actions from viewers", async () => {
    setup([makeReport()], "viewer");
    await screen.findByText(makeReport().name);
    for (const name of ["Nuevo informe", "Editar", "Eliminar"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "Acciones" })).not.toBeInTheDocument();
  });
  it("creates using the current user's tenant", async () => {
    setup();
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/reports/", async ({ request }) => {
        posted(await request.json());
        return HttpResponse.json(makeReport(), { status: 201 });
      }),
    );
    await screen.findByText(makeReport().name);
    await screen.findByRole("option", { name: asset.value });
    fireEvent.click(screen.getByRole("button", { name: /Nuevo informe/ }));
    const form = within(screen.getByRole("region", { name: "Nuevo informe" }));
    fireEvent.change(form.getByLabelText("Nombre"), { target: { value: " Ejecutivo " } });
    fireEvent.change(form.getByLabelText("Activo"), { target: { value: asset.id } });
    fireEvent.change(form.getByLabelText("Tipo"), { target: { value: "executive" } });
    fireEvent.click(form.getByRole("button", { name: "Crear informe" }));
    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith({
        tenant_id: makeUser().tenant_id,
        asset_id: asset.id,
        name: "Ejecutivo",
        report_type: "executive",
        summary: null,
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Nuevo informe" })).not.toBeInTheDocument(),
    );
  });
  it.each([
    ["Estado", "completed", "status"],
    ["Tipo", "technical", "report_type"],
  ])("filters %s on the server", async (label, value, key) => {
    setup();
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/reports/", ({ request }) => {
        const params = Object.fromEntries(new URL(request.url).searchParams);
        seen(params);
        return HttpResponse.json(
          reportList(params[key] ? [makeReport({ name: "Filtrado" })] : [makeReport()]),
        );
      }),
    );
    await screen.findByText(makeReport().name);
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(await screen.findByText("Filtrado")).toBeInTheDocument();
    expect(seen).toHaveBeenCalledWith({ offset: "0", limit: "20", [key]: value });
  });
  it("edits without sending immutable fields", async () => {
    setup();
    const patched = vi.fn();
    server.use(
      http.patch("*/api/v1/reports/:id", async ({ request, params }) => {
        patched(params.id, await request.json());
        return HttpResponse.json(makeReport({ name: "Editado", status: "completed" }));
      }),
    );
    await screen.findByText(makeReport().name);
    fireEvent.click(screen.getByRole("button", { name: "Editar" }));
    const form = within(screen.getByRole("region", { name: "Editar informe" }));
    expect(form.queryByLabelText("Activo")).not.toBeInTheDocument();
    expect(form.queryByLabelText("Tipo")).not.toBeInTheDocument();
    fireEvent.change(form.getByLabelText("Nombre"), { target: { value: "Editado" } });
    fireEvent.change(form.getByLabelText("Estado"), { target: { value: "completed" } });
    fireEvent.click(form.getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() =>
      expect(patched).toHaveBeenCalledWith(makeReport().id, {
        name: "Editado",
        status: "completed",
        summary: null,
      }),
    );
  });
  it("deletes only after confirmation", async () => {
    setup();
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/reports/:id", ({ params }) => {
        deleted(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await screen.findByText(makeReport().name);
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(deleted).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Eliminar informe" }));
    await waitFor(() => expect(deleted).toHaveBeenCalledWith(makeReport().id));
  });
});
