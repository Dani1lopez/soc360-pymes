import type { CSSProperties } from "react";

export type Mode = "dark" | "light";
export const palettes = [
  { name: "Medianoche", hue: 250, chroma: 0.035, primaryHue: 225 },
  { name: "Grafito", hue: 160, chroma: 0.004, primaryHue: 155 },
  { name: "Índigo", hue: 285, chroma: 0.055, primaryHue: 295 },
] as const;
export const severities = [
  { key: "critical", label: "Crítica", hue: 25, count: 12 },
  { key: "high", label: "Alta", hue: 55, count: 28 },
  { key: "medium", label: "Media", hue: 85, count: 46 },
  { key: "low", label: "Baja", hue: 250, count: 19 },
  { key: "info", label: "Informativa", hue: 240, count: 8 },
  { key: "ok", label: "Correcta", hue: 155, count: 34 },
] as const;
export type Severity = (typeof severities)[number]["key"];

export function theme(index: number, mode: Mode): CSSProperties {
  const palette = palettes[index] ?? palettes[0];
  const dark = mode === "dark";
  const base = (lightness: number) => `oklch(${lightness} ${palette.chroma} ${palette.hue})`;
  const foreground = base(dark ? 0.96 : 0.22);
  const primary = `oklch(${dark ? 0.8 : 0.46} 0.13 ${palette.primaryHue})`;
  const variables: Record<string, string> = {
    "--background": base(dark ? 0.16 : 0.97),
    "--foreground": foreground,
    "--card": base(dark ? 0.21 : 1),
    "--card-foreground": foreground,
    "--primary": primary,
    "--primary-foreground": base(dark ? 0.16 : 0.99),
    "--secondary": base(dark ? 0.28 : 0.92),
    "--secondary-foreground": foreground,
    "--muted": base(dark ? 0.25 : 0.94),
    "--muted-foreground": base(dark ? 0.76 : 0.44),
    "--accent": base(dark ? 0.32 : 0.9),
    "--accent-foreground": foreground,
    "--destructive": "oklch(0.53 0.19 25)",
    "--border": base(dark ? 0.32 : 0.85),
    "--input": base(dark ? 0.36 : 0.78),
    "--ring": primary,
  };
  // Badges use near-white on very dark tints, or near-black on pale tints.
  // Low chroma and wide lightness separation preserve >4.5:1 AA contrast.
  for (const severity of severities) {
    const chroma = severity.key === "info" ? 0.025 : 0.12;
    variables[`--sev-${severity.key}`] = `oklch(${dark ? 0.78 : 0.48} ${chroma} ${severity.hue})`;
    variables[`--sev-${severity.key}-tint`] =
      `oklch(${dark ? 0.28 : 0.94} ${palette.chroma / 3 + 0.015} ${severity.hue})`;
    variables[`--sev-${severity.key}-foreground`] =
      `oklch(${dark ? 0.96 : 0.22} 0.015 ${severity.hue})`;
  }
  return variables as CSSProperties;
}
