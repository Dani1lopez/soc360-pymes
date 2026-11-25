import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeEnrichment, makeEnrichmentItem } from "@/test/fixtures/vulnerabilities";
import { server } from "@/test/msw";
import {
  fetchVulnerabilityEnrichment,
  relaunchScanEnrichment,
  relaunchVulnerabilityEnrichment,
} from "./enrichment-api";

describe("fetchVulnerabilityEnrichment", () => {
  it("reads one item per function with the tenant level", async () => {
    server.use(
      http.get("*/api/v1/vulnerabilities/:id/enrichment", () =>
        HttpResponse.json(
          makeEnrichment([
            makeEnrichmentItem(),
            makeEnrichmentItem({ function: "impact", status: "pending", content: null }),
          ]),
        ),
      ),
    );

    const enrichment = await fetchVulnerabilityEnrichment("abc");

    expect(enrichment.level).toBe("standard");
    expect(enrichment.items.map((item) => item.function)).toEqual(["summary", "impact"]);
    expect(enrichment.items[1]?.status).toBe("pending");
  });
});

describe("relaunchVulnerabilityEnrichment", () => {
  it("posts and reports how much was queued", async () => {
    const called = vi.fn();
    server.use(
      http.post("*/api/v1/vulnerabilities/:id/enrichment", ({ params }) => {
        called(params.id);
        return HttpResponse.json({ queued: 3 });
      }),
    );

    await expect(relaunchVulnerabilityEnrichment("abc")).resolves.toEqual({ queued: 3 });
    expect(called).toHaveBeenCalledWith("abc");
  });
});

describe("relaunchScanEnrichment", () => {
  it("posts on the scan and reports queued against total", async () => {
    server.use(
      http.post("*/api/v1/scans/:id/enrichment", () => HttpResponse.json({ queued: 4, total: 7 })),
    );

    await expect(relaunchScanEnrichment("scan-1")).resolves.toEqual({ queued: 4, total: 7 });
  });
});
