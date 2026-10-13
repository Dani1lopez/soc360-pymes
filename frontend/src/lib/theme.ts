import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";
export const THEME_STORAGE_KEY = "soc360:theme";

export function readThemePreference(): ThemePreference {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

export function writeThemePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // Theme changes remain usable when storage is unavailable.
  }
}

export function resolveTheme(preference: ThemePreference, prefersDark: boolean): ResolvedTheme {
  return preference === "system" ? (prefersDark ? "dark" : "light") : preference;
}

export function applyTheme(resolved: ResolvedTheme): void {
  document.documentElement.classList.toggle("dark", resolved === "dark");
}

export function useTheme() {
  const [preference, updatePreference] = useState(readThemePreference);
  const [media] = useState(() => window.matchMedia("(prefers-color-scheme: dark)"));
  const [prefersDark, setPrefersDark] = useState(media.matches);
  const resolved = resolveTheme(preference, prefersDark);

  useEffect(() => {
    if (preference !== "system") return;
    const update = () => setPrefersDark(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [media, preference]);

  useEffect(() => applyTheme(resolved), [resolved]);

  function setPreference(next: ThemePreference): void {
    writeThemePreference(next);
    updatePreference(next);
  }

  return { preference, resolved, setPreference };
}
