import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { makeScan, scanList } from "@/test/fixtures/scans";
import { server } from "@/test/msw";
import { cancelScan, createScan, deleteScan, listScans, runScan, updateScan } from "./scans-api";

const tenantId = "00000000-0000-4000-8000-0000000000aa";
const assetId = "00000000-0000-4000-8000-000000000101";

describe("listScans", () => {
  it("sends the page and the asset filter", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/scans/", ({ request }) => {
        const params = new URL(request.url).searchParams;
        seen(Object.fromEntries(params));
        return HttpResponse.json(scanList([makeScan()]));
      }),
    );

    await listScans({ offset: 20, assetId });

    expect(seen).toHaveBeenCalledWith({ offset: "20", limit: "20", asset_id: assetId });
  });

  it("omits the asset filter when there is none", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/scans/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json(scanList([]));
      }),
    );

    await listScans({ offset: 0 });

    expect(seen).toHaveBeenCalledWith({ offset: "0", limit: "20" });
  });
});

describe("createScan", () => {
  it("posts the discriminated payload", async () => {
    const body = vi.fn();
    server.use(
      http.post("*/api/v1/scans/", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeScan({ status: "pending" }), { status: 201 });
      }),
    );

    const scan = await createScan({
      asset_id: assetId,
      name: "Chequeos web",
      tenant_id: tenantId,
      type: "web",
      config: { paths: ["/"] },
    });

    expect(body).toHaveBeenCalledWith({
      asset_id: assetId,
      name: "Chequeos web",
      tenant_id: tenantId,
      type: "web",
      config: { paths: ["/"] },
    });
    expect(scan.status).toBe("pending");
  });
});

describe("updateScan", () => {
  it("patches name, type and config", async () => {
    const body = vi.fn();
    server.use(
      http.patch("*/api/v1/scans/:id", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeScan({ name: "Nuevo nombre" }));
      }),
    );

    await updateScan("abc", { name: "Nuevo nombre", type: "discovery", config: {} });

    expect(body).toHaveBeenCalledWith({ name: "Nuevo nombre", type: "discovery", config: {} });
  });
});

describe("runScan", () => {
  it("accepts the 202 and returns the dispatched scan", async () => {
    server.use(
      http.post("*/api/v1/scans/:id/run", () =>
        HttpResponse.json(makeScan({ status: "pending" }), { status: 202 }),
      ),
    );

    await expect(runScan("abc")).resolves.toMatchObject({ status: "pending" });
  });

  it("surfaces a 409 as a conflict", async () => {
    server.use(
      http.post("*/api/v1/scans/:id/run", () =>
        HttpResponse.json({ detail: "scan is not dispatchable" }, { status: 409 }),
      ),
    );

    await expect(runScan("abc")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("cancelScan", () => {
  it("returns the cancelled scan", async () => {
    server.use(
      http.post("*/api/v1/scans/:id/cancel", () =>
        HttpResponse.json(makeScan({ status: "cancelled" })),
      ),
    );

    await expect(cancelScan("abc")).resolves.toMatchObject({ status: "cancelled" });
  });
});

describe("deleteScan", () => {
  it("accepts a 204", async () => {
    server.use(http.delete("*/api/v1/scans/:id", () => new HttpResponse(null, { status: 204 })));
    await expect(deleteScan("abc")).resolves.toBeUndefined();
  });
});
