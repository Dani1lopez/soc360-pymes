import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeOwnership } from "@/test/fixtures/assets";
import { server } from "@/test/msw";
import { approveOwnership } from "./ownership-api";

describe("approveOwnership", () => {
  it("posts to the approve endpoint of the asset and returns the declaration", async () => {
    const hit = vi.fn();
    server.use(
      http.post("*/api/v1/assets/:assetId/ownership/approve", ({ params }) => {
        hit(params.assetId);
        return HttpResponse.json(
          makeOwnership({
            status: "verified",
            approved_by_user_id: "00000000-0000-4000-8000-0000000000c1",
          }),
        );
      }),
    );

    const declaration = await approveOwnership("asset-1");

    expect(hit).toHaveBeenCalledWith("asset-1");
    expect(declaration.status).toBe("verified");
    expect(declaration.approved_by_user_id).toBe("00000000-0000-4000-8000-0000000000c1");
  });
});
