import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/**
 * Handlers base: lo que casi todos los tests necesitan antes de sus `server.use`.
 * `afterEach` llama a `resetHandlers()`, que los deja como estaban.
 */
export const handlers = [
  // Estado de propiedad (H2): sin declaración salvo que el test diga otra cosa.
  // Sin este handler, cada fila de activos haría una petición sin respuesta.
  http.get("*/api/v1/assets/:assetId/ownership", () => HttpResponse.json({ items: [], total: 0 })),
];

export const server = setupServer(...handlers);
