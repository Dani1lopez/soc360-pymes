import { apiFetch } from "@/api/client";
import type { DashboardSummary } from "@/api/schema";

/** Una sola llamada devuelve las cuatro métricas y la tendencia de 30 días. */
export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return apiFetch<DashboardSummary>("/api/v1/dashboard/summary");
}
