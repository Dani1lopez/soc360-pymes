import { describe, expect, it } from "vitest";
import { ASSET_TYPES, assetTypeLabel, assetValueHint, describeAssetError } from "./asset-types";

describe("assetTypeLabel", () => {
  it("labels every type of the backend enum", () => {
    expect(ASSET_TYPES).toHaveLength(6);
    expect(assetTypeLabel("ip")).toBe("Dirección IP");
    expect(assetTypeLabel("cloud_resource")).toBe("Recurso cloud");
  });

  it("falls back to the raw value for an unexpected type", () => {
    expect(assetTypeLabel("mainframe")).toBe("mainframe");
  });
});

describe("assetValueHint", () => {
  it("gives an example per type", () => {
    for (const type of ASSET_TYPES) {
      expect(assetValueHint(type)).not.toBe("");
    }
    expect(assetValueHint("subnet")).toContain("CIDR");
  });
});

describe("describeAssetError", () => {
  it("translates the backend contract messages", () => {
    expect(describeAssetError("value must be a valid FQDN")).toBe(
      "Introduce un dominio válido, por ejemplo acme-corp.example.",
    );
  });

  it("keeps an unknown message untouched", () => {
    expect(describeAssetError("boom")).toBe("boom");
  });
});
