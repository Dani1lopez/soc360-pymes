import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { makeVulnerability, vulnerabilityList } from "@/test/fixtures/vulnerabilities";
import { server } from "@/test/msw";
import {
  createVulnerability,
  deleteVulnerability,
  listVulnerabilities,
  updateVulnerability,
} from "./vulnerabilities-api";

const tenantId = "00000000-0000-4000-8000-0000000000aa";
const scanId = "00000000-0000-4000-8000-000000000201";

describe("listVulnerabilities", () => {
  it("sends the page and the scan filter", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/vulnerabilities/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json(vulnerabilityList([makeVulnerability()]));
      }),
    );

    const page = await listVulnerabilities({ offset: 20, scanId });

    expect(seen).toHaveBeenCalledWith({ offset: "20", limit: "20", scan_id: scanId });
    expect(page.items[0]?.title).toBe(makeVulnerability().title);
  });

  it("omits the scan filter when there is none", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/vulnerabilities/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json(vulnerabilityList([]));
      }),
    );

    await listVulnerabilities({ offset: 0 });
    expect(seen).toHaveBeenCalledWith({ offset: "0", limit: "20" });
  });
});

describe("createVulnerability", () => {
  it("posts the payload", async () => {
    const body = vi.fn();
    server.use(
      http.post("*/api/v1/vulnerabilities/", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeVulnerability(), { status: 201 });
      }),
    );

    await createVulnerability({
      tenant_id: tenantId,
      scan_id: scanId,
      title: "Hallazgo",
      severity: "high",
      cve_id: null,
      cvss_score: 7.5,
      description: null,
    });

    expect(body).toHaveBeenCalledWith({
      tenant_id: tenantId,
      scan_id: scanId,
      title: "Hallazgo",
      severity: "high",
      cve_id: null,
      cvss_score: 7.5,
      description: null,
    });
  });
});

describe("updateVulnerability", () => {
  it("patches the status only", async () => {
    const body = vi.fn();
    server.use(
      http.patch("*/api/v1/vulnerabilities/:id", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeVulnerability({ status: "fixed" }));
      }),
    );

    const updated = await updateVulnerability("abc", { status: "fixed" });

    expect(body).toHaveBeenCalledWith({ status: "fixed" });
    expect(updated.status).toBe("fixed");
  });

  it("surfaces a rejected status as a validation error", async () => {
    server.use(
      http.patch("*/api/v1/vulnerabilities/:id", () =>
        HttpResponse.json({ detail: "status cannot be null" }, { status: 422 }),
      ),
    );

    await expect(updateVulnerability("abc", { status: "open" })).rejects.toBeInstanceOf(ApiError);
  });
});

describe("deleteVulnerability", () => {
  it("accepts a 204", async () => {
    server.use(
      http.delete("*/api/v1/vulnerabilities/:id", () => new HttpResponse(null, { status: 204 })),
    );
    await expect(deleteVulnerability("abc")).resolves.toBeUndefined();
  });
});
