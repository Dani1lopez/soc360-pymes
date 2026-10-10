import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeReport, reportList } from "@/test/fixtures/reports";
import { server } from "@/test/msw";
import { createReport, deleteReport, listReports, updateReport } from "./reports-api";

describe("reports API", () => {
  it.each([
    [{ offset: 0 }, { offset: "0", limit: "20" }],
    [
      { offset: 20, limit: 10, assetId: "asset", reportType: "technical", status: "failed" },
      { offset: "20", limit: "10", asset_id: "asset", report_type: "technical", status: "failed" },
    ],
    [
      { offset: 0, assetId: "", reportType: null, status: null },
      { offset: "0", limit: "20" },
    ],
    [
      { offset: 0, status: "pending" },
      { offset: "0", limit: "20", status: "pending" },
    ],
  ])("sends only present filters %#", async (filters, expected) => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/reports/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json(reportList([makeReport()]));
      }),
    );
    expect((await listReports(filters)).items).toEqual([makeReport()]);
    expect(seen).toHaveBeenCalledWith(expected);
  });
  it("posts exact create payload", async () => {
    const seen = vi.fn();
    const report = makeReport();
    const input = {
      tenant_id: report.tenant_id,
      asset_id: report.asset_id,
      name: report.name,
      report_type: report.report_type,
      summary: null,
    };
    server.use(
      http.post("*/api/v1/reports/", async ({ request }) => {
        seen(await request.json());
        return HttpResponse.json(report, { status: 201 });
      }),
    );
    expect(await createReport(input)).toEqual(report);
    expect(seen).toHaveBeenCalledWith(input);
  });
  it("patches exact payload at the selected id", async () => {
    const seen = vi.fn();
    const input = { name: "Editado", status: "completed" as const, summary: "Resumen" };
    server.use(
      http.patch("*/api/v1/reports/:id", async ({ request, params }) => {
        seen(params.id, await request.json());
        return HttpResponse.json(makeReport(input));
      }),
    );
    expect(await updateReport("selected", input)).toEqual(makeReport(input));
    expect(seen).toHaveBeenCalledWith("selected", input);
  });
  it("accepts DELETE 204", async () => {
    const seen = vi.fn();
    server.use(
      http.delete("*/api/v1/reports/:id", ({ params }) => {
        seen(params.id);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await expect(deleteReport("selected")).resolves.toBeUndefined();
    expect(seen).toHaveBeenCalledWith("selected");
  });
});
