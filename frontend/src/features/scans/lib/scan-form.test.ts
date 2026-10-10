import { describe, expect, it } from "vitest";
import { makeScan } from "@/test/fixtures/scans";
import {
  emptyScanForm,
  formFromScan,
  hasScanFormErrors,
  toScanCreateInput,
  toScanUpdateInput,
  validateScanForm,
} from "./scan-form";

const tenantId = "00000000-0000-4000-8000-0000000000aa";
const assetId = "00000000-0000-4000-8000-000000000101";

describe("validateScanForm", () => {
  it("requires a name and an asset", () => {
    const errors = validateScanForm(emptyScanForm());
    expect(errors.name).toBe("Introduce un nombre.");
    expect(errors.assetId).toBe("Selecciona un activo.");
    expect(hasScanFormErrors(errors)).toBe(true);
  });

  it("rejects a name above the column length", () => {
    const errors = validateScanForm({ ...emptyScanForm(assetId), name: "a".repeat(256) });
    expect(errors.name).toContain("255");
  });

  it("asks for checks only when the type uses them", () => {
    const base = { ...emptyScanForm(assetId), name: "Escaneo" };
    expect(validateScanForm({ ...base, type: "discovery", checks: "" })).toEqual({});
    expect(validateScanForm({ ...base, type: "vulnerability", checks: "" }).checks).toBe(
      "Añade al menos una comprobación.",
    );
    expect(validateScanForm({ ...base, type: "full", checks: "" }).checks).toBeDefined();
  });

  it("asks for paths only when the type uses them", () => {
    const base = { ...emptyScanForm(assetId), name: "Escaneo" };
    expect(validateScanForm({ ...base, type: "vulnerability", paths: "" })).toEqual({});
    expect(validateScanForm({ ...base, type: "web", paths: "" }).paths).toBe(
      "Añade al menos una ruta.",
    );
  });

  it("accepts a complete form", () => {
    const state = { ...emptyScanForm(assetId), name: "Escaneo", checks: "tls", paths: "/" };
    expect(hasScanFormErrors(validateScanForm(state))).toBe(false);
  });
});

describe("toScanCreateInput", () => {
  it("builds the discovery branch", () => {
    const state = {
      ...emptyScanForm(assetId),
      name: "  Red interna  ",
      type: "discovery" as const,
    };
    expect(toScanCreateInput(state, tenantId)).toEqual({
      asset_id: assetId,
      name: "Red interna",
      tenant_id: tenantId,
      type: "discovery",
      config: { host_discovery: true },
    });
  });

  it("builds the vulnerability branch with normalised checks", () => {
    const state = {
      ...emptyScanForm(assetId),
      name: "Chequeos",
      type: "vulnerability" as const,
      checks: " tls , tls, headers ",
    };
    expect(toScanCreateInput(state, tenantId)).toMatchObject({
      type: "vulnerability",
      config: { checks: ["tls", "headers"] },
    });
  });

  it("builds the web branch", () => {
    const state = {
      ...emptyScanForm(assetId),
      name: "Web",
      type: "web" as const,
      paths: "/, /login",
    };
    expect(toScanCreateInput(state, tenantId)).toMatchObject({
      type: "web",
      config: { paths: ["/", "/login"] },
    });
  });

  it("builds the full branch with all three keys", () => {
    const state = {
      ...emptyScanForm(assetId),
      name: "Completo",
      type: "full" as const,
      hostDiscovery: false,
      checks: "tls",
      paths: "/",
    };
    expect(toScanCreateInput(state, tenantId)).toMatchObject({
      type: "full",
      config: { host_discovery: false, checks: ["tls"], paths: ["/"] },
    });
  });
});

describe("formFromScan / toScanUpdateInput", () => {
  it("round-trips the configuration of a full scan", () => {
    const scan = makeScan({
      type: "full",
      config: { host_discovery: false, checks: ["tls"], paths: ["/", "/login"] },
    });

    const state = formFromScan(scan);

    expect(state).toMatchObject({
      name: scan.name,
      type: "full",
      assetId: scan.asset_id,
      hostDiscovery: false,
      checks: "tls",
      paths: "/, /login",
    });
    expect(toScanUpdateInput(state)).toEqual({
      name: scan.name,
      type: "full",
      config: { host_discovery: false, checks: ["tls"], paths: ["/", "/login"] },
    });
  });

  it("defaults a missing config instead of rendering empty inputs", () => {
    const state = formFromScan(makeScan({ type: "discovery", config: null }));
    expect(state.hostDiscovery).toBe(true);
    expect(toScanUpdateInput(state).config).toEqual({ host_discovery: true });
  });
});
