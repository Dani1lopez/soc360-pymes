import { describe, expect, it } from "vitest";
import { makeScan } from "@/test/fixtures/scans";
import {
  canCancelScan,
  canRunScan,
  joinList,
  scanConfigSummary,
  scanStatusLabel,
  scanStatusTone,
  scanTypeLabel,
  splitList,
} from "./scan-labels";

describe("scanTypeLabel", () => {
  it("labels every type", () => {
    expect(scanTypeLabel("discovery")).toBe("Descubrimiento");
    expect(scanTypeLabel("vulnerability")).toBe("Vulnerabilidades");
    expect(scanTypeLabel("web")).toBe("Aplicación web");
    expect(scanTypeLabel("full")).toBe("Completo");
  });

  it("falls back to the raw value", () => {
    expect(scanTypeLabel("quantum")).toBe("quantum");
  });
});

describe("scanStatusLabel", () => {
  it("labels the five backend states", () => {
    expect(scanStatusLabel("pending")).toBe("Pendiente");
    expect(scanStatusLabel("running")).toBe("En ejecución");
    expect(scanStatusLabel("completed")).toBe("Completado");
    expect(scanStatusLabel("failed")).toBe("Fallido");
    expect(scanStatusLabel("cancelled")).toBe("Cancelado");
  });

  it("survives an unknown state and still returns a tone", () => {
    expect(scanStatusLabel("zombie")).toBe("Desconocido");
    expect(scanStatusTone("zombie")).toBe(scanStatusTone("pending"));
  });
});

describe("scanConfigSummary", () => {
  it("renders the config as readable pairs", () => {
    expect(scanConfigSummary({ host_discovery: true, checks: ["tls", "headers"] })).toBe(
      "host_discovery: true · checks: tls, headers",
    );
  });

  it("falls back to a dash", () => {
    expect(scanConfigSummary(null)).toBe("—");
    expect(scanConfigSummary({})).toBe("—");
    expect(scanConfigSummary("config")).toBe("—");
  });
});

describe("splitList / joinList", () => {
  it("trims, drops empties and removes duplicates", () => {
    expect(splitList(" tls, headers ,, tls ")).toEqual(["tls", "headers"]);
  });

  it("joins only arrays", () => {
    expect(joinList(["a", "b"])).toBe("a, b");
    expect(joinList(undefined)).toBe("");
    expect(joinList("a")).toBe("");
  });
});

describe("canRunScan / canCancelScan", () => {
  it("only runs pending scans", () => {
    expect(canRunScan(makeScan({ status: "pending" }))).toBe(true);
    expect(canRunScan(makeScan({ status: "running" }))).toBe(false);
    expect(canRunScan(makeScan({ status: "completed" }))).toBe(false);
  });

  it("cancels open scans only", () => {
    expect(canCancelScan(makeScan({ status: "pending" }))).toBe(true);
    expect(canCancelScan(makeScan({ status: "running" }))).toBe(true);
    expect(canCancelScan(makeScan({ status: "cancelled" }))).toBe(false);
    expect(canCancelScan(makeScan({ status: "failed" }))).toBe(false);
  });
});
