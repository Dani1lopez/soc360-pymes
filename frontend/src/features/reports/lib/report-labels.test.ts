import { describe, expect, it } from "vitest";
import { reportStatusLabel, reportStatusTone, reportTypeLabel } from "./report-labels";

describe("report labels", () => {
  it.each([
    ["vulnerability", "Vulnerabilidades"],
    ["executive", "Ejecutivo"],
    ["technical", "Técnico"],
    ["compliance", "Cumplimiento"],
  ])("labels type %s", (value, label) => expect(reportTypeLabel(value)).toBe(label));

  it.each([
    ["pending", "Pendiente", "bg-muted text-muted-foreground"],
    ["generating", "Generándose", "bg-primary/10 text-primary"],
    ["completed", "Completado", "bg-sev-ok-tint text-sev-ok-foreground"],
    ["failed", "Fallido", "bg-sev-critical-tint text-sev-critical-foreground"],
  ])("labels and tones status %s", (value, label, tone) => {
    expect(reportStatusLabel(value)).toBe(label);
    expect(reportStatusTone(value)).toBe(tone);
  });

  it.each(["future", "constructor", "__proto__"])("survives unknown %s", (value) => {
    expect(reportTypeLabel(value)).toBe(value);
    expect(reportStatusLabel(value)).toBe("Desconocido");
    expect(reportStatusTone(value)).toBe("bg-muted text-muted-foreground");
  });
});
