import { isApiError } from "@/api/errors";

/** Mensaje en español para cualquier error; los de la API ya vienen traducidos. */
export function errorMessage(
  error: unknown,
  fallback = "No se pudo completar la operación.",
): string {
  return isApiError(error) ? error.message : fallback;
}

/**
 * Mensaje de un campo concreto de un 422 de FastAPI. Acepta la ruta con o sin
 * el prefijo `body.` porque el backend no es consistente al respecto.
 */
export function fieldError(error: unknown, field: string): string | undefined {
  if (!isApiError(error) || error.kind !== "validation") return undefined;
  const match = error.fieldErrors.find(
    (item) => item.field === field || item.field === `body.${field}`,
  );
  return match?.message;
}
