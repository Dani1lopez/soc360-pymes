import { apiFetch } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { LoginRequest, UserResponse } from "@/api/schema";
import { acceptTokenResponse } from "@/api/session";

/** Sign in and keep the issued bearer in memory. API errors propagate as `ApiError`. */
export async function login(credentials: LoginRequest): Promise<void> {
  const body = await apiFetch<unknown>("/api/v1/auth/login", {
    method: "POST",
    body: credentials,
    auth: false,
  });
  if (acceptTokenResponse(body) === null) {
    throw new ApiError(502, "No se pudo iniciar sesión.");
  }
}

export function fetchCurrentUser(): Promise<UserResponse> {
  return apiFetch<UserResponse>("/api/v1/users/me");
}
