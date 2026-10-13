import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ThemeToggle } from "./theme-toggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

let matches = false;
let listeners: Set<() => void>;
beforeEach(() => {
  localStorage.clear();
  matches = false;
  listeners = new Set();
  vi.stubGlobal("matchMedia", () => ({
    get matches() {
      return matches;
    },
    addEventListener: (_event: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => listeners.delete(listener),
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark");
});

it("cycles light, dark, system with persistence and accessible labels", () => {
  localStorage.setItem(THEME_STORAGE_KEY, "light");
  render(<ThemeToggle />);
  expect(screen.getByRole("button", { name: "Tema: claro" }).textContent).toBe("Claro");
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("button", { name: "Tema: oscuro" }).textContent).toBe("Oscuro");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("button", { name: "Tema: según el sistema" }).textContent).toBe(
    "Sistema",
  );
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  fireEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("button", { name: "Tema: claro" })).toBeTruthy();
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  expect(listeners.size).toBe(0);
});

it("follows system changes and removes the listener on unmount", () => {
  const { unmount } = render(<ThemeToggle />);
  expect(listeners.size).toBe(1);
  act(() => {
    matches = true;
    listeners.forEach((listener) => listener());
  });
  expect(document.documentElement.classList.contains("dark")).toBe(true);
  act(() => {
    matches = false;
    listeners.forEach((listener) => listener());
  });
  expect(document.documentElement.classList.contains("dark")).toBe(false);
  unmount();
  expect(listeners.size).toBe(0);
});
