import type { TenantResponse } from "@/api/schema";

export function makeTenant(overrides: Partial<TenantResponse> = {}): TenantResponse {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    name: "Acme Corp",
    slug: "acme-corp",
    plan: "starter",
    max_assets: 20,
    is_active: true,
    settings: {
      notification_email: "admin@acme.com",
      scan_schedule: "0 2 * * *",
      severity_threshold: "medium",
      timezone: "Europe/Madrid",
      scan_limits: { daily_max: 10, concurrent_max: 2 },
      log_buffer_max: 500,
      baseline_reset_requested: false,
    },
    created_at: "2026-09-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    ...overrides,
  };
}
