import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ApiError } from "@/api/errors";
import { __resetSession, getBearer } from "@/api/session";
import { fetchCurrentUser, login } from "@/features/auth/api";
import { makeUser, sampleCredentials, tokenBody } from "@/features/auth/test-fixtures";
import { server } from "@/test/msw";

const credentials = sampleCredentials();

beforeEach(() => __resetSession());
afterEach(() => __resetSession());

describe("login", () => {
  it("posts the credentials as JSON and keeps the issued bearer", async () => {
    let received: unknown = null;
    server.use(
      http.post("*/api/v1/auth/login", async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(tokenBody("issued"));
      }),
    );

    await login(credentials);

    expect(received).toEqual(credentials);
    expect(getBearer()).toBe("issued");
  });

  it("rejects bad credentials without keeping a bearer", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json({ detail: "Credenciales incorrectas" }, { status: 401 }),
      ),
    );

    const error = await login(credentials).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "unauthorized", message: "Credenciales incorrectas" });
    expect(getBearer()).toBeNull();
  });

  it("exposes the lockout delay on 429", async () => {
    server.use(
      http.post("*/api/v1/auth/login", () =>
        HttpResponse.json(
          { detail: "Demasiados intentos. Intenta más tarde." },
          { status: 429, headers: { "Retry-After": "60" } },
        ),
      ),
    );

    await expect(login(credentials)).rejects.toMatchObject({
      kind: "rate_limited",
      retryAfterSeconds: 60,
    });
  });

  it("rejects a success response without a bearer", async () => {
    server.use(http.post("*/api/v1/auth/login", () => HttpResponse.json({ ok: true })));

    await expect(login(credentials)).rejects.toMatchObject({ status: 502 });
    expect(getBearer()).toBeNull();
  });
});

describe("fetchCurrentUser", () => {
  it("requests the profile with the bearer issued at login", async () => {
    let authorization: string | null = null;
    server.use(
      http.post("*/api/v1/auth/login", () => HttpResponse.json(tokenBody("issued"))),
      http.get("*/api/v1/users/me", ({ request }) => {
        authorization = request.headers.get("Authorization");
        return HttpResponse.json(makeUser());
      }),
    );

    await login(credentials);
    const user = await fetchCurrentUser();

    expect(authorization).toBe("Bearer issued");
    expect(user.email).toBe("ana@example.com");
  });
});
