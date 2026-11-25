import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Severity } from "@/api/schema";
import { SeverityBadge } from "./severity-badge";

test.each([
  ["critical", "Crítica", "lucide-octagon-alert"],
  ["high", "Alta", "lucide-triangle-alert"],
  ["medium", "Media", "lucide-circle-alert"],
  ["low", "Baja", "lucide-arrow-down"],
  ["info", "Informativa", "lucide-info"],
] as const)(
  "renders %s with a label, tone and distinct decorative icon",
  (severity, label, icon) => {
    render(<SeverityBadge severity={severity} />);
    const badge = screen.getByText(label);
    expect(badge).toHaveClass(`bg-sev-${severity}-tint`, `text-sev-${severity}-foreground`);
    expect(badge.querySelector(`.${icon}`)).toHaveAttribute("aria-hidden", "true");
  },
);

test.each(["emergency", null, undefined])(
  "falls back to a neutral badge for an unexpected severity (%s)",
  (value) => {
    render(<SeverityBadge severity={value as unknown as Severity} />);
    const badge = screen.getByText("Desconocida");
    expect(badge).toHaveClass("bg-muted", "text-muted-foreground");
    expect(badge.querySelector(".lucide-circle-help")).toHaveAttribute("aria-hidden", "true");
  },
);
