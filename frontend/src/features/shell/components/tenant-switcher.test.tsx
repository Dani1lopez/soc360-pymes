import { fireEvent, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { currentUserQueryKey } from "@/features/auth";
import { getActiveTenantId, setActiveTenantId } from "@/lib/active-tenant";
import { makeUser } from "@/test/fixtures/auth";
import { makeTenant } from "@/test/fixtures/tenants";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { AppShell } from "./app-shell";

afterEach(() => setActiveTenantId(null));

describe("TenantSwitcher", () => {
  it("lets a superadmin select and clear the active organization", async () => {
    const tenant = makeTenant();
    server.use(http.get("*/api/v1/tenants/", () => HttpResponse.json([tenant])));
    renderShell(
      <AppShell />,
      currentUserQueryKey,
      makeUser({ is_superadmin: true, tenant_id: null }),
    );
    expect(await screen.findByRole("option", { name: tenant.name })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Organización"), { target: { value: tenant.id } });
    expect(getActiveTenantId()).toBe(tenant.id);
    fireEvent.change(screen.getByLabelText("Organización"), { target: { value: "" } });
    expect(getActiveTenantId()).toBeNull();
  });

  it("does not show the selector for a normal admin", async () => {
    renderShell(<AppShell />, currentUserQueryKey, makeUser({ role: "admin" }));
    await screen.findByRole("banner");
    expect(screen.queryByLabelText("Organización")).not.toBeInTheDocument();
  });
});
