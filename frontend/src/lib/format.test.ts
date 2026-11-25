import { describe, expect, it } from "vitest";
import { formatCount, formatDate, formatDateTime, formatRatio, orDash } from "./format";

describe("formatDateTime", () => {
  it("formats a local instant as dd/mm/aaaa hh:mm", () => {
    const instant = new Date(2026, 9, 1, 9, 5).toISOString();
    expect(formatDateTime(instant)).toBe("01/10/2026 09:05");
  });

  it("returns a dash for missing or invalid values", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatDateTime("no-es-una-fecha")).toBe("—");
  });
});

describe("formatDate", () => {
  it("keeps only the date part", () => {
    const instant = new Date(2026, 9, 1, 9, 5).toISOString();
    expect(formatDate(instant)).toBe("01/10/2026");
  });

  it("returns a dash when there is no value", () => {
    expect(formatDate(null)).toBe("—");
  });
});

describe("formatRatio", () => {
  it("turns a ratio into a rounded percentage", () => {
    expect(formatRatio(0.8333)).toBe("83 %");
    expect(formatRatio(0)).toBe("0 %");
  });

  it("says there is no data when the ratio is null", () => {
    expect(formatRatio(null)).toBe("Sin datos");
  });
});

describe("formatCount", () => {
  it("groups thousands", () => {
    expect(formatCount(1234)).toBe("1.234");
    expect(formatCount(1234567)).toBe("1.234.567");
  });

  it("keeps small numbers, negatives and decimals readable", () => {
    expect(formatCount(12)).toBe("12");
    expect(formatCount(-1500)).toBe("-1.500");
    expect(formatCount(12.5)).toBe("12,5");
  });
});

describe("orDash", () => {
  it("falls back to a dash for empty values", () => {
    expect(orDash("hola")).toBe("hola");
    expect(orDash("")).toBe("—");
    expect(orDash(null)).toBe("—");
  });
});
