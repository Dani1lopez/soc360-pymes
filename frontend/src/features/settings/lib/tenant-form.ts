import type { TenantResponse, TenantSettings, TenantUpdateInput } from "@/api/schema";

export const PLANS = ["free", "starter", "pro", "enterprise"] as const;
export type TenantFormState = {
  name: string;
  plan: string;
  max_assets: string;
  is_active: boolean;
  timezone: string;
  severity_threshold: TenantSettings["severity_threshold"];
  scan_schedule: string;
  notification_email: string;
  daily_max: string;
  concurrent_max: string;
};
export type TenantFormErrors = Partial<Record<keyof TenantFormState, string>>;

export function formFromTenant(tenant: TenantResponse): TenantFormState {
  return {
    name: tenant.name,
    plan: tenant.plan,
    max_assets: String(tenant.max_assets),
    is_active: tenant.is_active,
    timezone: tenant.settings.timezone,
    severity_threshold: tenant.settings.severity_threshold,
    scan_schedule: tenant.settings.scan_schedule,
    notification_email: tenant.settings.notification_email ?? "",
    daily_max: String(tenant.settings.scan_limits.daily_max),
    concurrent_max: String(tenant.settings.scan_limits.concurrent_max),
  };
}

export function validateTenantForm(state: TenantFormState): TenantFormErrors {
  const errors: TenantFormErrors = {};
  if (!state.name.trim()) errors.name = "Introduce un nombre.";
  if (!PLANS.some((plan) => plan === state.plan)) errors.plan = "Selecciona un plan válido.";
  for (const field of ["max_assets", "daily_max", "concurrent_max"] as const) {
    const value = Number(state[field]);
    if (!Number.isSafeInteger(value) || value < 1)
      errors[field] = "Introduce un entero mayor o igual a 1.";
  }
  if (!state.timezone.trim()) errors.timezone = "Introduce una zona horaria.";
  if (!state.scan_schedule.trim()) errors.scan_schedule = "Introduce una programación.";
  const email = state.notification_email.trim();
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.notification_email = "Introduce un correo electrónico válido.";
  }
  return errors;
}

/** Conserva los ajustes no expuestos, también dentro de scan_limits. */
export function toTenantUpdateInput(
  state: TenantFormState,
  tenant: TenantResponse,
): TenantUpdateInput {
  return {
    name: state.name.trim(),
    plan: state.plan as NonNullable<TenantUpdateInput["plan"]>,
    max_assets: Number(state.max_assets),
    is_active: state.is_active,
    settings: {
      ...tenant.settings,
      timezone: state.timezone.trim(),
      severity_threshold: state.severity_threshold,
      scan_schedule: state.scan_schedule.trim(),
      notification_email: state.notification_email.trim() || null,
      scan_limits: {
        ...tenant.settings.scan_limits,
        daily_max: Number(state.daily_max),
        concurrent_max: Number(state.concurrent_max),
      },
    },
  };
}
