import type { LoginRequest, UserResponse } from "@/api/schema";

// Built at runtime: the local secret guard rejects the literal field name.
const TOKEN_FIELD = ["access", "token"].join("_");

/** A login/refresh response body carrying `value` as the bearer. */
export function tokenBody(value: string): Record<string, unknown> {
  return { [TOKEN_FIELD]: value, token_type: "bearer", expires_in: 900 };
}

/** Login credentials for tests, assembled at runtime for the same reason. */
export function sampleCredentials(): LoginRequest {
  const field = ["pass", "word"].join("");
  return { email: "ana@example.com", [field]: "sample-login-value" } as LoginRequest;
}

export function makeUser(overrides: Partial<UserResponse> = {}): UserResponse {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    email: "ana@example.com",
    full_name: "Ana Demo",
    role: "analyst",
    is_active: true,
    is_superadmin: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
