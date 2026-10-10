import { CheckCircle2, Clock, LoaderCircle, XCircle } from "lucide-react";
import type { ReportStatus } from "@/api/schema";
import { reportStatusLabel, reportStatusTone } from "../lib/report-labels";

const ICONS: Record<ReportStatus, typeof Clock> = {
  pending: Clock,
  generating: LoaderCircle,
  completed: CheckCircle2,
  failed: XCircle,
};

function isReportStatus(value: string): value is ReportStatus {
  return Object.hasOwn(ICONS, value);
}

/** Estado del informe con icono y texto: nunca solo por color. */
export function ReportStatusBadge({ status }: { status: string }) {
  const Icon = isReportStatus(status) ? ICONS[status] : Clock;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${reportStatusTone(status)}`}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {reportStatusLabel(status)}
    </span>
  );
}
