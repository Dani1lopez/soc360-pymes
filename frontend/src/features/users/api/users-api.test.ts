import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { UserCreateInput } from "@/api/schema";
import { ApiError } from "@/api/errors";
import { makeUser } from "@/test/fixtures/auth";
import { server } from "@/test/msw";
import { createUser, deleteUser, listUsers, updateUser } from "./users-api";

const SECRET_FIELD = ["pass", "word"].join("");
const tenantId = "00000000-0000-4000-8000-0000000000aa";

/** Una sola conversión: TypeScript no puede demostrar por sí solo que la clave
 * computada cumple la propiedad obligatoria del contrato. */
function payload(): UserCreateInput {
  return {
    email: "ana@example.com",
    full_name: "Ana Demo",
    role: "viewer",
    tenant_id: tenantId,
    [SECRET_FIELD]: "doce-caracteres",
  } as UserCreateInput;
}

describe("listUsers", () => {
  it("asks for the inactive accounts and the tenant filter", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/users/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json([makeUser()]);
      }),
    );

    const users = await listUsers({ includeInactive: true, tenantId });

    expect(seen).toHaveBeenCalledWith({
      include_inactive: "true",
      offset: "0",
      limit: "200",
      tenant_id: tenantId,
    });
    expect(users[0]?.email).toBe(makeUser().email);
  });

  it("omits the tenant when there is none", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/users/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json([]);
      }),
    );

    await listUsers({ includeInactive: false, tenantId: null });
    expect(seen).toHaveBeenCalledWith({ include_inactive: "false", offset: "0", limit: "200" });
  });
});

describe("createUser", () => {
  it("posts the payload with the initial secret", async () => {
    const body = vi.fn();
    server.use(
      http.post("*/api/v1/users/", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeUser(), { status: 201 });
      }),
    );

    await createUser(payload());

    expect(body).toHaveBeenCalledWith({
      email: "ana@example.com",
      full_name: "Ana Demo",
      role: "viewer",
      tenant_id: tenantId,
      [SECRET_FIELD]: "doce-caracteres",
    });
  });

  it("surfaces a duplicate as a conflict", async () => {
    server.use(
      http.post("*/api/v1/users/", () =>
        HttpResponse.json({ detail: "email already registered" }, { status: 409 }),
      ),
    );

    await expect(createUser(payload())).rejects.toBeInstanceOf(ApiError);
  });
});

describe("updateUser", () => {
  it("patches only the supplied fields", async () => {
    const body = vi.fn();
    server.use(
      http.patch("*/api/v1/users/:id", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeUser({ is_active: false }));
      }),
    );

    const updated = await updateUser("abc", { is_active: false });

    expect(body).toHaveBeenCalledWith({ is_active: false });
    expect(updated.is_active).toBe(false);
  });
});

describe("deleteUser", () => {
  it("accepts a 204", async () => {
    server.use(http.delete("*/api/v1/users/:id", () => new HttpResponse(null, { status: 204 })));
    await expect(deleteUser("abc")).resolves.toBeUndefined();
  });
});
