import { describe, expect, it } from "vitest";
import type { AssetType } from "@/api/schema";
import { validateAssetValue } from "./asset-validation";

describe("validateAssetValue", () => {
  it("requires a value", () => {
    expect(validateAssetValue("ip", "   ")).toBe("Introduce un valor.");
  });

  it("rejects values above the column length", () => {
    expect(validateAssetValue("hostname", "a".repeat(256))).toContain("255");
  });

  it.each<[AssetType, string[]]>([
    ["ip", ["192.0.2.10", "2001:db8::1"]],
    ["domain", ["acme-corp.example"]],
    ["hostname", ["vpn.acme-corp.example", "localhost"]],
    ["web_app", ["https://app.acme-corp.example", "http://10.0.0.5:8080"]],
    ["subnet", ["10.20.30.0/24", "2001:db8::/32"]],
    ["cloud_resource", ["arn:aws:s3:::acme-corp-backups"]],
  ])("accepts a valid %s value", (type, values) => {
    for (const value of values) {
      expect(validateAssetValue(type, value)).toBeNull();
    }
  });

  it.each<[AssetType, string]>([
    ["ip", "300.1.1.1"],
    ["ip", "no-es-una-ip"],
    ["domain", "sin-punto"],
    ["hostname", "-vpn.example"],
    ["web_app", "ftp://app.example"],
    ["web_app", "app.example"],
    ["subnet", "10.20.30.0/33"],
    ["subnet", "10.20.30.0"],
    ["cloud_resource", "s3://acme-corp-backups"],
  ])("rejects an invalid %s value", (type, value) => {
    expect(validateAssetValue(type, value)).toBe(
      "El valor no es válido para el tipo seleccionado.",
    );
  });

  it("tolerates surrounding whitespace", () => {
    expect(validateAssetValue("domain", "  acme-corp.example  ")).toBeNull();
  });

  it("rejects a trailing dot as a domain, as the backend does", () => {
    expect(validateAssetValue("domain", "acme-corp.example.")).toBe(
      "El valor no es válido para el tipo seleccionado.",
    );
  });
});
