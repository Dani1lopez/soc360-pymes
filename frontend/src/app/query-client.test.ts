import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/errors";
import { createQueryClient, shouldRetryQuery } from "@/app/query-client";

describe("shouldRetryQuery", () => {
  it.each([0, 500, 502, 503])("retries a transient failure once (status %i)", (status) => {
    const error = new ApiError(status, "transient");
    expect(shouldRetryQuery(0, error)).toBe(true);
    expect(shouldRetryQuery(1, error)).toBe(false);
  });

  it.each([400, 401, 403, 404, 409, 422, 429])("never retries a client error (%i)", (status) => {
    expect(shouldRetryQuery(0, new ApiError(status, "client"))).toBe(false);
  });

  it("retries an unexpected error once", () => {
    expect(shouldRetryQuery(0, new Error("boom"))).toBe(true);
    expect(shouldRetryQuery(1, new Error("boom"))).toBe(false);
  });
});

describe("createQueryClient", () => {
  it("uses the selective retry policy for queries", () => {
    const client = createQueryClient();
    expect(client.getDefaultOptions().queries?.retry).toBe(shouldRetryQuery);
  });
});
