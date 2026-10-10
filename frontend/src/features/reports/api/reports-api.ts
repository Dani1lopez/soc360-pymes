import { apiFetch } from "@/api/client";
import type { Paginated, ReportCreateInput, ReportResponse, ReportUpdateInput } from "@/api/schema";

const BASE = "/api/v1/reports";

/** Tamaño de página de la tabla (el backend admite de 1 a 200). */
export const REPORTS_PAGE_SIZE = 20;

/** Filtros que acepta el listado: activo, tipo y estado. */
export type ReportFilters = {
  offset: number;
  limit?: number;
  assetId?: string | null;
  reportType?: string | null;
  status?: string | null;
};

export function listReports({
  offset,
  limit = REPORTS_PAGE_SIZE,
  assetId,
  reportType,
  status,
}: ReportFilters): Promise<Paginated<ReportResponse>> {
  const query = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (assetId) query.set("asset_id", assetId);
  if (reportType) query.set("report_type", reportType);
  if (status) query.set("status", status);
  return apiFetch<Paginated<ReportResponse>>(`${BASE}/?${query.toString()}`);
}

export function fetchReport(id: string): Promise<ReportResponse> {
  return apiFetch<ReportResponse>(`${BASE}/${id}`);
}

export function createReport(input: ReportCreateInput): Promise<ReportResponse> {
  return apiFetch<ReportResponse>(`${BASE}/`, { method: "POST", body: input });
}

export function updateReport(id: string, input: ReportUpdateInput): Promise<ReportResponse> {
  return apiFetch<ReportResponse>(`${BASE}/${id}`, { method: "PATCH", body: input });
}

export function deleteReport(id: string): Promise<void> {
  return apiFetch<void>(`${BASE}/${id}`, { method: "DELETE" });
}
