import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyTheme,
  readThemePreference,
  resolveTheme,
  THEME_STORAGE_KEY,
  writeThemePreference,
} from "./theme";

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.classList.remove("dark");
});

describe("theme preferences", () => {
  it("defaults missing and invalid preferences to system", () => {
    expect(readThemePreference()).toBe("system");
    localStorage.setItem(THEME_STORAGE_KEY, "invalid");
    expect(readThemePreference()).toBe("system");
  });
  it("reads and writes explicit preferences and removes system", () => {
    for (const preference of ["light", "dark"] as const) {
      writeThemePreference(preference);
      expect(readThemePreference()).toBe(preference);
    }
    writeThemePreference("system");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });
  it("tolerates inaccessible storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("Unavailable");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("Unavailable");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("Unavailable");
    });
    expect(readThemePreference()).toBe("system");
    expect(() => writeThemePreference("dark")).not.toThrow();
    expect(() => writeThemePreference("system")).not.toThrow();
  });
  it.each([true, false])("resolves preferences with system dark=%s", (dark) => {
    expect(resolveTheme("system", dark)).toBe(dark ? "dark" : "light");
    expect(resolveTheme("light", dark)).toBe("light");
    expect(resolveTheme("dark", dark)).toBe("dark");
  });
  it("toggles the root dark class", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});
