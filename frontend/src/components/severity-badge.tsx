import { ArrowDown, CircleAlert, Info, OctagonAlert, TriangleAlert } from "lucide-react";
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

export function SeverityBadge({ severity }: { severity: Severity }) {
  const { tone, icon: Icon } = styles[severity];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}
    >
      <Icon aria-hidden="true" className="size-3.5" />
      {SEVERITY_LABELS[severity]}
    </span>
  );
}
