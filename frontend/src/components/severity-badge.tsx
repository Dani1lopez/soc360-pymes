import {
  ArrowDown,
  CircleAlert,
  CircleHelp,
  Info,
  OctagonAlert,
  TriangleAlert,
} from "lucide-react";
import type { Severity } from "@/api/schema";

// Public labels are part of the badge's presentational contract.
// eslint-disable-next-line react-refresh/only-export-components
export const SEVERITY_LABELS = {
  critical: "Crítica",
  high: "Alta",
  medium: "Media",
  low: "Baja",
  info: "Informativa",
} satisfies Record<Severity, string>;

const styles = {
  critical: { tone: "bg-sev-critical-tint text-sev-critical-foreground", icon: OctagonAlert },
  high: { tone: "bg-sev-high-tint text-sev-high-foreground", icon: TriangleAlert },
  medium: { tone: "bg-sev-medium-tint text-sev-medium-foreground", icon: CircleAlert },
  low: { tone: "bg-sev-low-tint text-sev-low-foreground", icon: ArrowDown },
  info: { tone: "bg-sev-info-tint text-sev-info-foreground", icon: Info },
};

// API data is only typed at compile time: a value outside the enum must not
// break the page, so it renders a neutral, explicitly unknown badge.
const unknownSeverity = {
  tone: "bg-muted text-muted-foreground",
  icon: CircleHelp,
  label: "Desconocida",
};

function isSeverity(value: unknown): value is Severity {
  return typeof value === "string" && Object.hasOwn(styles, value);
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const {
    tone,
    icon: Icon,
    label,
  } = isSeverity(severity)
    ? { ...styles[severity], label: SEVERITY_LABELS[severity] }
    : unknownSeverity;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {label}
    </span>
  );
}
