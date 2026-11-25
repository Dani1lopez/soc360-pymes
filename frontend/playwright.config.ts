import { defineConfig, devices } from "@playwright/test";

/**
 * Smoke E2E contra la API y el servidor de Vite reales (decisión D7 del estudio
 * F4). No arranca los servidores: en desarrollo suele haber ya uno en marcha, así
 * que se espera a que respondan en `E2E_BASE_URL` (por defecto el Vite de siempre).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
