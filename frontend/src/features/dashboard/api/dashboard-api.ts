import { apiFetch } from "@/api/client";
import type { DashboardSummary } from "@/api/schema";

/** Una sola llamada devuelve las cuatro métricas y la tendencia de 30 días. */
export function fetchDashboardSummary(tenantId?: string): Promise<DashboardSummary> {
  const query = tenantId === undefined ? "" : `?tenant_id=${encodeURIComponent(tenantId)}`;
  return apiFetch<DashboardSummary>(`/api/v1/dashboard/summary${query}`);
}
