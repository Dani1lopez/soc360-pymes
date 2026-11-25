import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { makeAsset } from "@/test/fixtures/assets";
import { server } from "@/test/msw";
import { createAsset, deleteAsset, exportAssetsCsv, listAssets, updateAsset } from "./assets-api";

describe("listAssets", () => {
  it("sends offset and limit and parses the envelope", async () => {
    const request = vi.fn();
    server.use(
      http.get("*/api/v1/assets/", ({ request: req }) => {
        request(new URL(req.url).searchParams);
        return HttpResponse.json({ items: [makeAsset()], total: 1, limit: 20, offset: 0 });
      }),
    );

    const page = await listAssets({ offset: 0 });

    expect(request).toHaveBeenCalledWith(new URLSearchParams({ offset: "0", limit: "20" }));
    expect(page.items[0]?.value).toBe("acme-corp.example");
    expect(page.total).toBe(1);
  });
});

describe("exportAssetsCsv", () => {
  it("reads the export as text, not JSON", async () => {
    server.use(
      http.get("*/api/v1/assets/", ({ request }) => {
        expect(new URL(request.url).searchParams.get("export")).toBe("csv");
        return new HttpResponse("id,type\n1,domain", {
          headers: { "Content-Type": "text/csv" },
        });
      }),
    );

    await expect(exportAssetsCsv()).resolves.toBe("id,type\n1,domain");
  });
});

describe("createAsset", () => {
  it("posts the payload and returns the created asset", async () => {
    const body = vi.fn();
    server.use(
      http.post("*/api/v1/assets/", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeAsset(), { status: 201 });
      }),
    );

    const asset = await createAsset({
      tenant_id: "00000000-0000-4000-8000-0000000000aa",
      type: "domain",
      value: "acme-corp.example",
    });

    expect(body).toHaveBeenCalledWith({
      tenant_id: "00000000-0000-4000-8000-0000000000aa",
      type: "domain",
      value: "acme-corp.example",
    });
    expect(asset.id).toBe(makeAsset().id);
  });
});

describe("updateAsset", () => {
  it("patches only the supplied fields", async () => {
    const body = vi.fn();
    server.use(
      http.patch("*/api/v1/assets/:id", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeAsset({ value: "nuevo.example" }));
      }),
    );

    const asset = await updateAsset("abc", { value: "nuevo.example" });

    expect(body).toHaveBeenCalledWith({ value: "nuevo.example" });
    expect(asset.value).toBe("nuevo.example");
  });
});

describe("deleteAsset", () => {
  it("accepts a 204 without body", async () => {
    server.use(http.delete("*/api/v1/assets/:id", () => new HttpResponse(null, { status: 204 })));
    await expect(deleteAsset("abc")).resolves.toBeUndefined();
  });
});

describe("errors", () => {
  it("surfaces a duplicate as a conflict", async () => {
    server.use(
      http.post("*/api/v1/assets/", () =>
        HttpResponse.json({ detail: "duplicate asset" }, { status: 409 }),
      ),
    );

    await expect(
      createAsset({
        tenant_id: "00000000-0000-4000-8000-0000000000aa",
        type: "domain",
        value: "acme-corp.example",
      }),
    ).rejects.toBeInstanceOf(ApiError);
  });
});
