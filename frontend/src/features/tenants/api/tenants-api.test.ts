import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeTenant } from "@/test/fixtures/tenants";
import { server } from "@/test/msw";
import { fetchTenant, listTenants, updateTenant } from "./tenants-api";

describe("listTenants", () => {
  it("reads the plain array and asks for a wide page", async () => {
    const seen = vi.fn();
    server.use(
      http.get("*/api/v1/tenants/", ({ request }) => {
        seen(Object.fromEntries(new URL(request.url).searchParams));
        return HttpResponse.json([makeTenant()]);
      }),
    );

    const tenants = await listTenants();

    expect(seen).toHaveBeenCalledWith({ limit: "200" });
    expect(tenants[0]?.slug).toBe("acme-corp");
  });
});

describe("fetchTenant", () => {
  it("reads one organisation by id", async () => {
    server.use(
      http.get("*/api/v1/tenants/:id", ({ params }) =>
        HttpResponse.json(makeTenant({ id: String(params.id) })),
      ),
    );

    await expect(fetchTenant("tenant-1")).resolves.toMatchObject({ id: "tenant-1" });
  });
});

describe("updateTenant", () => {
  it("patches the full configuration", async () => {
    const body = vi.fn();
    server.use(
      http.patch("*/api/v1/tenants/:id", async ({ request }) => {
        body(await request.json());
        return HttpResponse.json(makeTenant({ name: "Acme Renombrada" }));
      }),
    );

    const tenant = makeTenant();
    const updated = await updateTenant(tenant.id, {
      name: "Acme Renombrada",
      settings: tenant.settings,
    });

    expect(body).toHaveBeenCalledWith({ name: "Acme Renombrada", settings: tenant.settings });
    expect(updated.name).toBe("Acme Renombrada");
  });
});
