import { Ban, CheckCircle2, Clock, LoaderCircle, XCircle } from "lucide-react";
import type { ScanStatus } from "@/api/schema";
import { scanStatusLabel, scanStatusTone } from "../lib/scan-labels";

const ICONS: Record<ScanStatus, typeof Clock> = {
  pending: Clock,
  running: LoaderCircle,
  completed: CheckCircle2,
  failed: XCircle,
  cancelled: Ban,
};

function isScanStatus(value: string): value is ScanStatus {
  return Object.hasOwn(ICONS, value);
}

/** Estado del escaneo con icono y texto: nunca solo por color. */
export function ScanStatusBadge({ status }: { status: string }) {
  const Icon = isScanStatus(status) ? ICONS[status] : Clock;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${scanStatusTone(status)}`}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {scanStatusLabel(status)}
    </span>
  );
}
