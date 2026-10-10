import { apiFetch } from "@/api/client";
import type { TenantResponse, TenantUpdateInput } from "@/api/schema";

const BASE = "/api/v1/tenants";

/**
 * Listado de organizaciones. Es de superadministrador y responde con un array
 * plano, sin el sobre de paginación del resto de la API.
 */
export function listTenants(): Promise<TenantResponse[]> {
  return apiFetch<TenantResponse[]>(`${BASE}/?limit=200`);
}

/** Cualquier rol puede leer su propia organización; el superadmin, cualquiera. */
export function fetchTenant(tenantId: string): Promise<TenantResponse> {
  return apiFetch<TenantResponse>(`${BASE}/${tenantId}`);
}

/** Solo superadministrador. El cuerpo lleva la configuración completa. */
export function updateTenant(tenantId: string, input: TenantUpdateInput): Promise<TenantResponse> {
  return apiFetch<TenantResponse>(`${BASE}/${tenantId}`, { method: "PATCH", body: input });
}
