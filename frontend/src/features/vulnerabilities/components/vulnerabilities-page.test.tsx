import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { Role, VulnerabilityResponse } from "@/api/schema";
import { currentUserQueryKey } from "@/features/auth";
import { makeAsset } from "@/test/fixtures/assets";
import { makeUser } from "@/test/fixtures/auth";
import { makeScan } from "@/test/fixtures/scans";
import { makeVulnerability, vulnerabilityList } from "@/test/fixtures/vulnerabilities";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { VulnerabilitiesPage } from "./vulnerabilities-page";

const asset = makeAsset();
const scan = makeScan({ asset_id: asset.id });

function setup(
  items: VulnerabilityResponse[],
  {
    role = "admin",
    onList,
  }: { role?: Role; onList?: (params: Record<string, string>) => void } = {},
) {
  server.use(
    http.get("*/api/v1/scans/", () =>
      HttpResponse.json({ items: [scan], total: 1, limit: 200, offset: 0 }),
    ),
    http.get("*/api/v1/assets/", () =>
      HttpResponse.json({ items: [asset], total: 1, limit: 200, offset: 0 }),
    ),
    http.get("*/api/v1/vulnerabilities/", ({ request }) => {
      const params = Object.fromEntries(new URL(request.url).searchParams);
      onList?.(params);
      return HttpResponse.json(vulnerabilityList(items, { offset: Number(params.offset ?? 0) }));
    }),
  );
  return renderShell(<VulnerabilitiesPage />, currentUserQueryKey, makeUser({ role }));
}

describe("VulnerabilitiesPage", () => {
  it("lists findings with severity, status, CVSS, CVE and asset", async () => {
    setup([
      makeVulnerability(),
      makeVulnerability({
        id: "2",
        title: "HSTS ausente",
        severity: "high",
        status: "fixed",
        cvss_score: 7,
        cve_id: null,
      }),
    ]);

    expect(await screen.findByText("Inyección SQL en el buscador")).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("Crítica")).toBeInTheDocument();
    expect(within(table).getByText("Abierta")).toBeInTheDocument();
    expect(within(table).getByText("Corregida")).toBeInTheDocument();
    expect(within(table).getByText("9.8")).toBeInTheDocument();
    expect(within(table).getByText("7.0")).toBeInTheDocument();
    expect(within(table).getByText("CVE-2026-12345")).toBeInTheDocument();
    expect(within(table).getAllByText(asset.value)).toHaveLength(2);
  });

  it("filters the loaded page by status and severity", async () => {
    setup([
      makeVulnerability({ id: "1", title: "Abierta crítica" }),
      makeVulnerability({ id: "2", title: "Corregida crítica", status: "fixed" }),
      makeVulnerability({ id: "3", title: "Abierta baja", severity: "low" }),
    ]);

    await screen.findByText("Abierta crítica");
    fireEvent.change(screen.getByLabelText("Mostrar"), { target: { value: "open" } });

    expect(screen.queryByText("Corregida crítica")).not.toBeInTheDocument();
    expect(screen.getByText("Abierta baja")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Filtrar por severidad"), {
      target: { value: "critical" },
    });
    expect(screen.queryByText("Abierta baja")).not.toBeInTheDocument();
    expect(screen.getByText("Abierta crítica")).toBeInTheDocument();
  });

  it("shows an empty state when there is nothing", async () => {
    setup([]);
    expect(await screen.findByText("No hay hallazgos")).toBeInTheDocument();
  });

  it("hides write actions from a viewer", async () => {
    setup([makeVulnerability()], { role: "viewer" });

    await screen.findByText("Inyección SQL en el buscador");
    expect(screen.queryByRole("button", { name: /Registrar hallazgo/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Eliminar" })).not.toBeInTheDocument();
  });

  it("registers a finding with the selected scan", async () => {
    setup([makeVulnerability()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/vulnerabilities/", async ({ request }) => {
        posted(await request.json());
        return HttpResponse.json(makeVulnerability(), { status: 201 });
      }),
    );

    await screen.findByText("Inyección SQL en el buscador");
    fireEvent.click(screen.getByRole("button", { name: /Registrar hallazgo/ }));
    fireEvent.change(screen.getByLabelText("Escaneo"), { target: { value: scan.id } });
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Puerto abierto" } });
    fireEvent.change(screen.getByLabelText("Severidad"), { target: { value: "medium" } });
    fireEvent.change(screen.getByLabelText(/^CVSS/), { target: { value: "6,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar hallazgo" }));

    await waitFor(() =>
      expect(posted).toHaveBeenCalledWith({
        tenant_id: makeUser().tenant_id,
        scan_id: scan.id,
        title: "Puerto abierto",
        severity: "medium",
        cve_id: null,
        cvss_score: 6.5,
        description: null,
      }),
    );
  });

  it("rejects an incomplete form without calling the API", async () => {
    setup([makeVulnerability()]);
    const posted = vi.fn();
    server.use(
      http.post("*/api/v1/vulnerabilities/", () => {
        posted();
        return HttpResponse.json(makeVulnerability(), { status: 201 });
      }),
    );

    await screen.findByText("Inyección SQL en el buscador");
    fireEvent.click(screen.getByRole("button", { name: /Registrar hallazgo/ }));
    fireEvent.click(screen.getByRole("button", { name: "Guardar hallazgo" }));

    expect(await screen.findByText("Introduce un título.")).toBeInTheDocument();
    expect(posted).not.toHaveBeenCalled();
  });

  it("filters by scan on the server and resets the page", async () => {
    const requests: Record<string, string>[] = [];
    setup([makeVulnerability()], { onList: (params) => requests.push(params) });

    await screen.findByText("Inyección SQL en el buscador");
    fireEvent.change(screen.getByLabelText("Filtrar por escaneo"), {
      target: { value: scan.id },
    });

    await waitFor(() =>
      expect(requests.some((params) => params.scan_id === scan.id && params.offset === "0")).toBe(
        true,
      ),
    );
  });

  it("deletes a finding after confirming", async () => {
    setup([makeVulnerability()]);
    const deleted = vi.fn();
    server.use(
      http.delete("*/api/v1/vulnerabilities/:id", ({ params }) => {
        deleted(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );

    await screen.findByText("Inyección SQL en el buscador");
    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    fireEvent.click(screen.getByRole("button", { name: "Eliminar hallazgo" }));

    await waitFor(() => expect(deleted).toHaveBeenCalledWith(makeVulnerability().id));
  });
});
