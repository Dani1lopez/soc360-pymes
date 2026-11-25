import { describe, expect, it } from "vitest";
import { ApiError, isApiError, networkError, parseApiError } from "./errors";

function response(detail: unknown, status = 422, retryAfter?: string) {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: retryAfter ? { "Retry-After": retryAfter } : {},
  });
}

describe("API errors", () => {
  it("passes through Spanish string details", async () => {
    expect((await parseApiError(response("Sin permiso", 403))).message).toBe("Sin permiso");
  });

  it("passes through English string details for client errors", async () => {
    expect((await parseApiError(response("Invalid credentials", 401))).message).toBe(
      "Invalid credentials",
    );
  });

  it("replaces the server-provided text of 5xx errors with a Spanish generic", async () => {
    const unavailable = await parseApiError(response("service temporarily unavailable", 503));
    expect(unavailable.kind).toBe("unavailable");
    expect(unavailable.message).toBe("Error del servidor. Inténtalo de nuevo más tarde.");

    const internal = await parseApiError(response("psycopg2 OperationalError at 10.0.0.5", 500));
    expect(internal.message).toBe("Error del servidor. Inténtalo de nuevo más tarde.");
  });

  it("falls back to the generic message when the string detail is blank", async () => {
    expect((await parseApiError(response("", 400))).message).toBe(
      "No se pudo completar la solicitud.",
    );
    expect((await parseApiError(response("   ", 403))).message).toBe(
      "No se pudo completar la solicitud.",
    );
  });

  it("maps multiple validation fields including nested indices", async () => {
    const error = await parseApiError(
      response([
        { type: "missing", loc: ["body", "email"], msg: "Field required" },
        { type: "missing", loc: ["body", "items", 0, "name"], msg: "Field required" },
      ]),
    );
    expect(error.kind).toBe("validation");
    expect(error.message).toBe("Revisa los campos del formulario.");
    expect(error.fieldErrors).toEqual([
      { field: "email", message: "Campo obligatorio" },
      { field: "items.0.name", message: "Campo obligatorio" },
    ]);
  });

  it.each([
    ["missing", {}, "Field required", "Campo obligatorio"],
    ["string_too_short", { min_length: 3 }, "Too short", "Mínimo 3 caracteres"],
    ["string_too_long", { max_length: 8 }, "Too long", "Máximo 8 caracteres"],
    ["greater_than_equal", { ge: 0 }, "Too small", "Debe ser como mínimo 0"],
    ["less_than_equal", { le: 10 }, "Too large", "Debe ser como máximo 10"],
    ["value_error", {}, "Value error, Valor inválido", "Valor inválido"],
    ["unknown_type", {}, "Original message", "Original message"],
  ])("maps Pydantic type %s", async (type, ctx, msg, message) => {
    const error = await parseApiError(response([{ type, ctx, msg, loc: ["body", "value"] }]));
    expect(error.fieldErrors).toEqual([{ field: "value", message }]);
  });

  it.each([
    ["string_too_short", { min_length: "3" }],
    ["string_too_long", {}],
    ["greater_than_equal", { ge: null }],
    ["less_than_equal", { le: "10" }],
  ])("rejects nonnumeric context for %s", async (type, ctx) => {
    const error = await parseApiError(response([{ type, ctx, msg: "Original", loc: [] }]));
    expect(error.fieldErrors).toEqual([{ field: "", message: "Original" }]);
  });

  it("never includes validation input values", async () => {
    const error = await parseApiError(
      response([
        {
          type: "missing",
          loc: ["body", "password"],
          msg: "Field required",
          input: "secret-token-123",
        },
      ]),
    );
    expect(JSON.stringify({ message: error.message, fields: error.fieldErrors })).not.toContain(
      "secret-token-123",
    );
  });

  it.each(["body", "query", "path", "header", "cookie"])("drops source %s", async (source) => {
    const error = await parseApiError(
      response([{ type: "missing", loc: [source], msg: "Required" }]),
    );
    expect(error.fieldErrors[0]?.field).toBe("");
  });

  it("preserves locations without a source prefix", async () => {
    const error = await parseApiError(
      response([{ type: "missing", loc: ["items", 0], msg: "Required" }]),
    );
    expect(error.fieldErrors[0]?.field).toBe("items.0");
  });

  it.each([
    [429, "rate_limited"],
    [503, "unavailable"],
  ])("reads retry seconds for %s", async (status, kind) => {
    const error = await parseApiError(response("Inténtalo más tarde.", status as number, "30"));
    expect(error.kind).toBe(kind);
    expect(error.retryAfterSeconds).toBe(30);
  });

  it.each(["Wed, 21 Oct 2015 07:28:00 GMT", "-5", "garbage", "1.5"])(
    "ignores Retry-After %s",
    async (header) => {
      expect((await parseApiError(response("Wait", 503, header))).retryAfterSeconds).toBeNull();
    },
  );

  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [409, "conflict"],
    [400, "client"],
  ])("classifies status %s", async (status, kind) => {
    expect((await parseApiError(response("Error", status as number))).kind).toBe(kind);
  });

  it("hides HTML server error bodies", async () => {
    const error = await parseApiError(new Response("<html>proxy failure</html>", { status: 502 }));
    expect(error.kind).toBe("server");
    expect(error.message).toBe("Error del servidor. Inténtalo de nuevo más tarde.");
    expect(error.message).not.toContain("<html>");
  });

  it.each([
    [204, "unknown"],
    [500, "server"],
  ])("handles empty status %s", async (status, kind) => {
    const error = await parseApiError(new Response(null, { status: status as number }));
    expect(error.kind).toBe(kind);
    expect(error.message).toBe(
      status === 500
        ? "Error del servidor. Inténtalo de nuevo más tarde."
        : "No se pudo completar la solicitud.",
    );
  });

  it("tolerates invalid JSON", async () => {
    expect((await parseApiError(new Response('{"detail":', { status: 400 }))).message).toBe(
      "No se pudo completar la solicitud.",
    );
  });

  it.each([{}, 42, null])("handles unknown detail shape %j", async (detail) => {
    expect((await parseApiError(response(detail, 429))).message).toBe(
      "Demasiados intentos. Inténtalo más tarde.",
    );
    expect((await parseApiError(response(detail, 500))).message).toBe(
      "Error del servidor. Inténtalo de nuevo más tarde.",
    );
    expect((await parseApiError(response(detail, 400))).message).toBe(
      "No se pudo completar la solicitud.",
    );
  });

  it("tolerates malformed validation items", async () => {
    const error = await parseApiError(response([null, 5, {}, { loc: "body", msg: 12 }]));
    expect(error.fieldErrors).toEqual([]);
  });

  it("reads the body only once", async () => {
    const input = response("Error", 400);
    await parseApiError(input);
    expect(input.bodyUsed).toBe(true);
    expect((await parseApiError(input)).message).toBe("No se pudo completar la solicitud.");
  });

  it("creates safe network errors and identifies ApiError instances", async () => {
    const error = networkError(new TypeError("secret connection info"));
    expect(error).toBeInstanceOf(Error);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.kind).toBe("network");
    expect(error.message).toBe("No se pudo conectar con el servidor.");
    expect(error.fieldErrors).toEqual([]);
    expect(error.retryAfterSeconds).toBeNull();
    expect(networkError().kind).toBe("network");
    expect(isApiError(error)).toBe(true);
    expect(isApiError(new Error())).toBe(false);
    expect(isApiError(null)).toBe(false);
    expect(isApiError({ kind: "network" })).toBe(false);
    expect((await parseApiError(Response.error())).kind).toBe("network");
  });
});
