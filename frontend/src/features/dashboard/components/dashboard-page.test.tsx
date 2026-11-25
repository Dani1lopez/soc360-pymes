import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { setActiveTenantId } from "@/lib/active-tenant";
import { currentUserQueryKey } from "@/features/auth";
import { makeUser } from "@/test/fixtures/auth";
import { makeDashboardSummary } from "@/test/fixtures/dashboard";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { DashboardPage } from "./dashboard-page";

function setup({ calls = vi.fn() }: { calls?: () => void } = {}) {
  server.use(
    http.get("*/api/v1/dashboard/summary", () => {
      calls();
      return HttpResponse.json(makeDashboardSummary());
    }),
  );
  return renderShell(<DashboardPage />, currentUserQueryKey, makeUser({ role: "analyst" }));
}

afterEach(() => setActiveTenantId(null));

describe("DashboardPage", () => {
  it("does not request a summary until a superadmin selects an organization", async () => {
    const calls = vi.fn();
    server.use(
      http.get("*/api/v1/dashboard/summary", () => {
        calls();
        return HttpResponse.json(makeDashboardSummary());
      }),
    );
    renderShell(
      <DashboardPage />,
      currentUserQueryKey,
      makeUser({ is_superadmin: true, tenant_id: null }),
    );
    expect(
      await screen.findByText("Selecciona una organización en la cabecera para ver el panel."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actualizar/ })).not.toBeInTheDocument();
    expect(calls).not.toHaveBeenCalled();
  });

  it.each([true, false])("scopes the request only for superadmins (%s)", async (isSuperadmin) => {
    setActiveTenantId("selected-tenant");
    const urls: URL[] = [];
    server.use(
      http.get("*/api/v1/dashboard/summary", ({ request }) => {
        urls.push(new URL(request.url));
        return HttpResponse.json(makeDashboardSummary());
      }),
    );
    const { queryClient } = renderShell(
      <DashboardPage />,
      currentUserQueryKey,
      makeUser({
        role: "admin",
        is_superadmin: isSuperadmin,
        ...(isSuperadmin ? { tenant_id: null } : {}),
      }),
    );
    await screen.findByText("Activos vigilados");
    expect(urls).toHaveLength(1);
    expect(urls[0]?.search).toBe(isSuperadmin ? "?tenant_id=selected-tenant" : "");
    expect(
      queryClient.getQueryData(["dashboard", "summary", isSuperadmin ? "selected-tenant" : "own"]),
    ).toBeDefined();
  });
  it("shows the four metrics with their hints", async () => {
    setup();

    expect(await screen.findByText("Activos vigilados")).toBeInTheDocument();
    expect(screen.getByText("5").tagName).toBe("DD");
    expect(screen.getByText("2 escaneados en las últimas 24 h")).toBeInTheDocument();
    expect(screen.getByText("Hallazgos abiertos")).toBeInTheDocument();
    expect(screen.getByText("11").tagName).toBe("DD");
    expect(screen.getByText("2 críticos")).toBeInTheDocument();
    expect(screen.getByText("40 %")).toBeInTheDocument();
    expect(screen.getByText("2 de 5 activos")).toBeInTheDocument();
    expect(screen.getByText("83 %")).toBeInTheDocument();
    expect(screen.getByText("5 correctos · 1 fallidos")).toBeInTheDocument();
  });

  it("greets the signed-in user", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: /Hola, Ana/ })).toBeInTheDocument();
  });

  it("describes both charts for screen readers and in text", async () => {
    setup();

    const trend = await screen.findByRole("img", { name: /Tendencia de los últimos 30 días/ });
    expect(trend).toHaveAccessibleName(/12 hallazgos abiertos y 4 cerrados/);
    expect(screen.getByText("Abiertos: 12 · Cerrados: 4")).toBeInTheDocument();

    const severity = screen.getByRole("img", { name: /Hallazgos abiertos por severidad/ });
    expect(severity).toHaveAccessibleName(/Crítica 2/);
    expect(screen.getAllByRole("listitem").some((item) => item.textContent === "Crítica: 2")).toBe(
      true,
    );
  });

  it("points a new tenant at the first step", async () => {
    server.use(
      http.get("*/api/v1/dashboard/summary", () =>
        HttpResponse.json(
          makeDashboardSummary({
            assets_monitored: 0,
            open_by_severity: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
            coverage_24h: { covered: 0, total: 0, ratio: null, since: "2026-10-09T15:00:00Z" },
            scan_success_30d: {
              completed: 0,
              failed: 0,
              ratio: null,
              since: "2026-09-10T15:00:00Z",
            },
            trend_30d: [],
          }),
        ),
      ),
    );
    renderShell(<DashboardPage />, currentUserQueryKey, makeUser({ role: "admin" }));

    expect(await screen.findByText(/Todavía no hay datos/)).toBeInTheDocument();
    expect(screen.getAllByText("Sin datos")).toHaveLength(2);
  });

  it("shows the API error with a working retry", async () => {
    setup();
    server.use(
      http.get("*/api/v1/dashboard/summary", () => new HttpResponse(null, { status: 503 }), {
        once: true,
      }),
    );

    renderShell(<DashboardPage />, currentUserQueryKey, makeUser({ role: "admin" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pudieron cargar los datos");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Activos vigilados")).toBeInTheDocument();
  });

  it("refetches on demand", async () => {
    const calls = vi.fn();
    setup({ calls });

    await screen.findByText("Activos vigilados");
    expect(calls).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Actualizar/ }));

    await waitFor(() => expect(calls).toHaveBeenCalledTimes(2));
  });
});
