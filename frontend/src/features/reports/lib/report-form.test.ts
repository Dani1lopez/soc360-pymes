import { describe, expect, it } from "vitest";
import { makeReport } from "@/test/fixtures/reports";
import {
  emptyReportForm,
  formFromReport,
  toReportCreateInput,
  toReportUpdateInput,
  validateReportForm,
} from "./report-form";

describe("report form", () => {
  it("requires name and asset", () => {
    expect(validateReportForm({ ...emptyReportForm(), name: "  " })).toEqual({
      name: "Introduce un nombre.",
      assetId: "Selecciona el activo del informe.",
    });
  });
  it("accepts 255 characters but rejects 256", () => {
    const base = emptyReportForm("asset");
    expect(validateReportForm({ ...base, name: "a".repeat(255) })).toEqual({});
    expect(validateReportForm({ ...base, name: "a".repeat(256) }).name).toContain("255");
  });
  it("normalizes create payload and omits status", () => {
    expect(
      toReportCreateInput(
        { ...emptyReportForm("asset"), name: " Informe ", summary: "  " },
        "tenant",
      ),
    ).toEqual({
      tenant_id: "tenant",
      asset_id: "asset",
      name: "Informe",
      report_type: "vulnerability",
      summary: null,
    });
  });
  it("sends only mutable fields on update", () => {
    expect(
      toReportUpdateInput({
        ...emptyReportForm("changed"),
        name: " Editado ",
        reportType: "technical",
        status: "completed",
        summary: " texto ",
      }),
    ).toEqual({
      name: "Editado",
      status: "completed",
      summary: "texto",
    });
    expect(
      toReportUpdateInput({ ...emptyReportForm(), name: "Informe", summary: " " }).summary,
    ).toBeNull();
  });
  it("seeds all fields and normalizes missing summary", () => {
    const report = makeReport();
    expect(formFromReport(report)).toEqual({
      name: report.name,
      assetId: report.asset_id,
      reportType: report.report_type,
      status: report.status,
      summary: "",
    });
    expect(formFromReport(makeReport({ summary: "Resumen" })).summary).toBe("Resumen");
  });
});
