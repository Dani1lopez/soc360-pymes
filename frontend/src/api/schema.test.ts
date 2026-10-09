import { describe, expectTypeOf, it } from "vitest";
import type { ApiSchemas, ApiPaths } from "@/api/schema";

// Compile-time contract checks: `pnpm typecheck` fails when the generated
// types stop matching the shapes the client depends on.
describe("generated API types", () => {
  it("keeps the login response shape the session logic relies on", () => {
    expectTypeOf<ApiSchemas["TokenResponse"]["access_token"]>().toEqualTypeOf<string>();
    expectTypeOf<ApiSchemas["TokenResponse"]["expires_in"]>().toEqualTypeOf<number>();
  });

  it("exposes the auth endpoints used for the session lifecycle", () => {
    expectTypeOf<ApiPaths>().toHaveProperty("/api/v1/auth/login");
    expectTypeOf<ApiPaths>().toHaveProperty("/api/v1/auth/refresh");
    expectTypeOf<ApiPaths>().toHaveProperty("/api/v1/auth/logout");
  });
});
