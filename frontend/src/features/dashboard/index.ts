export { DashboardPage } from "./components/dashboard-page";
export {
  dashboardQueryKey,
  dashboardQueryOptions,
  useDashboardSummary,
} from "./hooks/use-dashboard";

// `TrendChart` y `SeverityChart` no se reexportan a propósito: arrastrarían
// Recharts al paquete de quien importe este índice, y `dashboard-page` los carga
// con `lazy()` para que vivan en su propio trozo.
