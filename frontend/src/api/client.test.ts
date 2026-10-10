import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./client";
import { ApiError } from "./errors";
import { __resetSession, getBearer, setBearer } from "./session";

const ISSUED_KEY = ["access", "token"].join("_");

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function issued(value: string): Record<string, unknown> {
  return { [ISSUED_KEY]: value, token_type: "bearer", expires_in: 900 };
}

function headersOf(call: unknown[] | undefined): Headers {
  return new Headers((call?.[1] as RequestInit | undefined)?.headers);
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  __resetSession();
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  __resetSession();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("apiFetch", () => {
  it("attaches the in-memory bearer and reads JSON", async () => {
    setBearer("abc");
    fetchMock.mockResolvedValue(json({ value: 7 }));

    await expect(apiFetch<{ value: number }>("/api/v1/assets")).resolves.toEqual({ value: 7 });
    expect(headersOf(fetchMock.mock.calls[0]).get("Authorization")).toBe("Bearer abc");
  });

  it("omits the Authorization header without a session", async () => {
    fetchMock.mockResolvedValue(json({}));
    await apiFetch("/api/v1/assets");
    expect(headersOf(fetchMock.mock.calls[0]).get("Authorization")).toBeNull();
  });

  it("serializes a JSON body with its content type", async () => {
    fetchMock.mockResolvedValue(json({}));

    await apiFetch("/api/v1/assets", { method: "POST", body: { name: "web" } });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(init.body).toBe('{"name":"web"}');
    expect(headersOf(fetchMock.mock.calls[0]).get("Content-Type")).toBe("application/json");
    expect(init.credentials).toBe("include");
  });

  it("refreshes once and retries a 401 with the new bearer", async () => {
    setBearer("stale");
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Sesión caducada" }, 401))
      .mockResolvedValueOnce(json(issued("fresh")))
      .mockResolvedValueOnce(json({ value: 1 }));

    await expect(apiFetch<{ value: number }>("/api/v1/assets")).resolves.toEqual({ value: 1 });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(headersOf(fetchMock.mock.calls[2]).get("Authorization")).toBe("Bearer fresh");
  });

  it("does not refresh a second time when the retry also returns 401", async () => {
    setBearer("stale");
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Sesión caducada" }, 401))
      .mockResolvedValueOnce(json(issued("fresh")))
      .mockResolvedValueOnce(json({ detail: "Sesión caducada" }, 401));

    await expect(apiFetch("/api/v1/assets")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("never refreshes for public endpoints", async () => {
    fetchMock.mockResolvedValueOnce(json({ detail: "Credenciales incorrectas" }, 401));

    await expect(
      apiFetch("/api/v1/auth/login", { method: "POST", body: {}, auth: false }),
    ).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("surfaces the original error and clears the session when the refresh is rejected", async () => {
    setBearer("stale");
    fetchMock
      .mockResolvedValueOnce(json({ detail: "Sesión caducada" }, 401))
      .mockResolvedValueOnce(json({ detail: "no" }, 401));

    await expect(apiFetch("/api/v1/assets")).rejects.toThrow("Sesión caducada");
    expect(getBearer()).toBeNull();
  });

  it("returns undefined for an empty 204", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(apiFetch("/api/v1/assets/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("parses a non-ok response into an ApiError", async () => {
    fetchMock.mockResolvedValue(json({ detail: "Sin permiso" }, 403));

    const error = await apiFetch("/api/v1/assets").catch((cause: unknown) => cause);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 403, kind: "forbidden", message: "Sin permiso" });
  });

  it("maps a transport failure to a network ApiError", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(apiFetch("/api/v1/assets")).rejects.toMatchObject({
      status: 0,
      kind: "network",
    });
  });

  it("rejects a malformed success body with an ApiError", async () => {
    fetchMock.mockResolvedValue(new Response("<html>", { status: 200 }));

    await expect(apiFetch("/api/v1/assets")).rejects.toBeInstanceOf(ApiError);
  });
});
