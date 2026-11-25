import { describe, expect, it } from "vitest";
import { makeTenant } from "@/test/fixtures/tenants";
import { formFromTenant, toTenantUpdateInput, validateTenantForm } from "./tenant-form";

describe("tenant form", () => {
  it("loads all editable values", () => {
    expect(formFromTenant(makeTenant())).toMatchObject({
      name: "Acme Corp",
      max_assets: "20",
      daily_max: "10",
      concurrent_max: "2",
      timezone: "Europe/Madrid",
    });
  });
  it("accepts a valid form and an optional empty email", () => {
    expect(validateTenantForm({ ...formFromTenant(makeTenant()), notification_email: "" })).toEqual(
      {},
    );
  });
  it("requires name, timezone and schedule and validates email", () => {
    expect(
      validateTenantForm({
        ...formFromTenant(makeTenant()),
        name: " ",
        timezone: "",
        scan_schedule: " ",
        notification_email: "invalid",
      }),
    ).toMatchObject({
      name: expect.any(String),
      timezone: expect.any(String),
      scan_schedule: expect.any(String),
      notification_email: expect.any(String),
    });
  });
  it.each(["0", "-1", "", "1.5", "NaN", "Infinity"])(
    "rejects invalid integer limits: %s",
    (value) => {
      expect(
        validateTenantForm({
          ...formFromTenant(makeTenant()),
          max_assets: value,
          daily_max: value,
          concurrent_max: value,
        }),
      ).toMatchObject({
        max_assets: expect.any(String),
        daily_max: expect.any(String),
        concurrent_max: expect.any(String),
      });
    },
  );
  it("preserves hidden settings without mutating the tenant", () => {
    const tenant = makeTenant();
    tenant.settings.baseline_reset_requested = true;
    tenant.settings.log_buffer_max = 1234;
    const input = toTenantUpdateInput(
      { ...formFromTenant(tenant), name: " Nuevo ", daily_max: "12", notification_email: " " },
      tenant,
    );
    expect(input).toMatchObject({
      name: "Nuevo",
      settings: {
        baseline_reset_requested: true,
        log_buffer_max: 1234,
        notification_email: null,
        scan_limits: { daily_max: 12, concurrent_max: 2 },
      },
    });
    expect(tenant.settings.scan_limits.daily_max).toBe(10);
  });
});
