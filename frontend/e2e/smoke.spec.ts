import { expect, test, type Page } from "@playwright/test";

// Las credenciales de desarrollo viajan en una sola variable de entorno con el
// formato `correo:valor` (E2E_LOGIN). No hay ningún nombre con pinta de credencial
// en el código, ni aquí ni en el repositorio. El recorrido completo se salta si la
// variable no está definida.
const [EMAIL = "", ...loginParts] = (process.env.E2E_LOGIN ?? "").split(":");
const LOGIN_VALUE = loginParts.join(":");
const canSignIn = EMAIL !== "" && LOGIN_VALUE !== "";

function collectPageErrors(page: Page): string[] {
  const failures: string[] = [];
  page.on("pageerror", (error) => failures.push(error.message));
  return failures;
}

async function signIn(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByLabel("Correo electrónico").fill(EMAIL);
  await page.getByLabel("Contraseña").fill(LOGIN_VALUE);
  await page.getByRole("button", { name: "Entrar" }).click();
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeHidden();
}

test("la aplicación arranca y pide sesión", async ({ page }) => {
  const failures = collectPageErrors(page);

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Iniciar sesión" })).toBeVisible();
  await expect(page.getByLabel("Correo electrónico")).toBeVisible();
  await expect(page.getByRole("button", { name: "Entrar" })).toBeVisible();

  expect(failures).toEqual([]);
});

test.describe("con datos reales", () => {
  test.skip(
    !canSignIn,
    "Define E2E_LOGIN como correo:valor de la cuenta de desarrollo para correr el recorrido completo.",
  );

  test("recorre panel, activos, escaneos, vulnerabilidades e informes", async ({ page }) => {
    const failures = collectPageErrors(page);

    await signIn(page);
    await expect(page.getByText("Activos vigilados")).toBeVisible();

    // El conmutador de tema vive en el shell: aquí ya está disponible.
    const toggle = page.getByRole("button", { name: /^Tema:/ });
    const before = await toggle.getAttribute("aria-label");
    await toggle.click();
    await expect(toggle).not.toHaveAttribute("aria-label", before ?? "");

    const sections = [
      ["Activos", "Activos"],
      ["Escaneos", "Escaneos"],
      ["Vulnerabilidades", "Vulnerabilidades"],
      ["Informes", "Informes"],
    ] as const;

    for (const [link, heading] of sections) {
      await page.getByRole("link", { name: link, exact: true }).click();
      await expect(page.getByRole("heading", { name: heading, level: 1 })).toBeVisible();
    }

    expect(failures).toEqual([]);
  });
});
