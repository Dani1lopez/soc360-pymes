/// <reference types="node" />
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const INDEX_CSS_PATH = resolve(dirname(fileURLToPath(import.meta.url)), "index.css");
const css = readFileSync(INDEX_CSS_PATH, "utf8");

interface OklchColor {
  l: number;
  c: number;
  h: number;
}

function extractBlock(source: string, selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`, "m").exec(source);
  const body = match?.[1];
  if (body === undefined) {
    throw new Error(`Missing CSS block for ${selector}`);
  }
  return body;
}

function parseVars(block: string): Record<string, string> {
  const vars: Record<string, string> = {};
  const regex = /(--[a-z0-9-]+)\s*:\s*([^;]+);/gi;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(block)) !== null) {
    const key = match[1];
    const value = match[2];
    if (key !== undefined && value !== undefined) {
      vars[key] = value.trim();
    }
  }
  return vars;
}

function requireVar(vars: Record<string, string>, name: string): string {
  const value = vars[name];
  if (value === undefined) {
    throw new Error(`Missing CSS variable ${name}`);
  }
  return value;
}

function parseOklch(value: string): OklchColor {
  const match = /^oklch\(\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\)$/.exec(value);
  if (!match) {
    throw new Error(`Expected oklch(L C H) token, got: ${value}`);
  }
  return {
    l: Number(match[1]),
    c: Number(match[2]),
    h: Number(match[3]),
  };
}

function oklchToLinearRgb({ l, c, h }: OklchColor): [number, number, number] {
  const hRad = (h * Math.PI) / 180;
  const a = c * Math.cos(hRad);
  const b = c * Math.sin(hRad);

  const l_ = l + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = l - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = l - 0.0894841775 * a - 1.291485548 * b;

  const l3 = l_ * l_ * l_;
  const m3 = m_ * m_ * m_;
  const s3 = s_ * s_ * s_;

  const r = Math.min(1, Math.max(0, 4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3));
  const g = Math.min(1, Math.max(0, -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3));
  const bl = Math.min(1, Math.max(0, -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3));

  return [r, g, bl];
}

function relativeLuminance(color: OklchColor): number {
  const [r, g, b] = oklchToLinearRgb(color);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrastRatio(fg: string, bg: string): number {
  const l1 = relativeLuminance(parseOklch(fg));
  const l2 = relativeLuminance(parseOklch(bg));
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

const REQUIRED_COLOR_TOKENS = [
  "--background",
  "--foreground",
  "--card",
  "--card-foreground",
  "--primary",
  "--primary-foreground",
  "--secondary",
  "--secondary-foreground",
  "--muted",
  "--muted-foreground",
  "--accent",
  "--accent-foreground",
  "--destructive",
  "--border",
  "--input",
  "--ring",
  "--sev-critical",
  "--sev-critical-tint",
  "--sev-critical-foreground",
  "--sev-high",
  "--sev-high-tint",
  "--sev-high-foreground",
  "--sev-medium",
  "--sev-medium-tint",
  "--sev-medium-foreground",
  "--sev-low",
  "--sev-low-tint",
  "--sev-low-foreground",
  "--sev-info",
  "--sev-info-tint",
  "--sev-info-foreground",
  "--sev-ok",
  "--sev-ok-tint",
  "--sev-ok-foreground",
] as const;

const CONTRAST_PAIRS: ReadonlyArray<[string, string]> = [
  ["--foreground", "--background"],
  ["--card-foreground", "--card"],
  ["--primary-foreground", "--primary"],
  ["--secondary-foreground", "--secondary"],
  ["--muted-foreground", "--background"],
  ["--muted-foreground", "--card"],
  ["--accent-foreground", "--accent"],
  ["--sev-critical-foreground", "--sev-critical-tint"],
  ["--sev-high-foreground", "--sev-high-tint"],
  ["--sev-medium-foreground", "--sev-medium-tint"],
  ["--sev-low-foreground", "--sev-low-tint"],
  ["--sev-info-foreground", "--sev-info-tint"],
  ["--sev-ok-foreground", "--sev-ok-tint"],
];

describe("D1 visual foundation tokens (index.css)", () => {
  const themeVars = parseVars(extractBlock(css, "@theme inline"));
  const lightVars = parseVars(extractBlock(css, ":root"));
  const darkVars = parseVars(extractBlock(css, ".dark"));

  it("declares Instrument Sans for UI and JetBrains Mono for technical data", () => {
    expect(requireVar(themeVars, "--font-sans")).toContain("Instrument Sans");
    expect(requireVar(themeVars, "--font-mono")).toContain("JetBrains Mono");
  });

  it("enables tabular numerals in base typography rules", () => {
    expect(css).toContain("tabular-nums");
  });

  it("defines all required semantic tokens in both :root and .dark", () => {
    for (const token of REQUIRED_COLOR_TOKENS) {
      expect(lightVars[token], `light ${token}`).toBeDefined();
      expect(darkVars[token], `dark ${token}`).toBeDefined();
    }
  });

  it("uses neutral mineral graphite (dark) and warm technical paper (light) instead of slate-blue", () => {
    const lightBg = parseOklch(requireVar(lightVars, "--background"));
    const darkBg = parseOklch(requireVar(darkVars, "--background"));

    expect(lightBg.l).toBeGreaterThanOrEqual(0.96);
    expect(lightBg.c).toBeLessThanOrEqual(0.015);

    expect(darkBg.l).toBeLessThanOrEqual(0.16);
    expect(darkBg.c).toBeLessThanOrEqual(0.015);
  });

  it("uses copper/amber as the primary functional accent in both modes", () => {
    const lightPrimary = parseOklch(requireVar(lightVars, "--primary"));
    const darkPrimary = parseOklch(requireVar(darkVars, "--primary"));

    expect(lightPrimary.h).toBeGreaterThanOrEqual(45);
    expect(lightPrimary.h).toBeLessThanOrEqual(75);
    expect(lightPrimary.c).toBeGreaterThanOrEqual(0.11);

    expect(darkPrimary.h).toBeGreaterThanOrEqual(45);
    expect(darkPrimary.h).toBeLessThanOrEqual(75);
    expect(darkPrimary.c).toBeGreaterThanOrEqual(0.11);
  });

  it("maintains WCAG AA (>= 4.5:1) contrast on all text and severity badge pairs", () => {
    for (const [fg, bg] of CONTRAST_PAIRS) {
      const lightRatio = contrastRatio(requireVar(lightVars, fg), requireVar(lightVars, bg));
      const darkRatio = contrastRatio(requireVar(darkVars, fg), requireVar(darkVars, bg));

      expect(lightRatio, `light ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
      expect(darkRatio, `dark ${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });
});
