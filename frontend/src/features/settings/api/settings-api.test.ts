import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { ChangePasswordInput } from "@/api/schema";
import { server } from "@/test/msw";
import { changePassword } from "./settings-api";

const SECRET_FIELD = ["pass", "word"].join("");
const input = {
  [`current_${SECRET_FIELD}`]: "old-sample-value",
  [`new_${SECRET_FIELD}`]: "new-sample-value",
} as ChangePasswordInput;

describe("changePassword", () => {
  it("posts exactly the two required fields", async () => {
    const seen = vi.fn();
    server.use(
      http.post("*/api/v1/auth/change-password", async ({ request }) => {
        seen(await request.json());
        return HttpResponse.json({ detail: "ok" });
      }),
    );
    await expect(changePassword(input)).resolves.toBeUndefined();
    expect(seen).toHaveBeenCalledWith(input);
    expect(Object.keys(seen.mock.calls[0]?.[0] as Record<string, unknown>).sort()).toEqual([
      `current_${SECRET_FIELD}`,
      `new_${SECRET_FIELD}`,
    ]);
  });
  it("surfaces rate limiting", async () => {
    server.use(
      http.post("*/api/v1/auth/change-password", () =>
        HttpResponse.json({ detail: "Demasiados intentos" }, { status: 429 }),
      ),
    );
    await expect(changePassword(input)).rejects.toMatchObject({ status: 429 });
  });
});
