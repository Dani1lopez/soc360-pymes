import { ApiError, networkError, parseApiError } from "@/api/errors";
import { getBearer, refreshSession } from "@/api/session";

export interface ApiRequestOptions extends Omit<RequestInit, "body" | "headers"> {
  /** Plain data serialized as JSON. */
  body?: unknown;
  headers?: HeadersInit;
  /** Set false for public endpoints (login, refresh): no bearer and no retry. */
  auth?: boolean;
}

function buildInit(options: ApiRequestOptions): RequestInit {
  const { body, auth = true, headers, ...rest } = options;
  const merged = new Headers(headers);
  const init: RequestInit = { ...rest, credentials: "include", headers: merged };
  if (body !== undefined) {
    if (!merged.has("Content-Type")) merged.set("Content-Type", "application/json");
    init.body = JSON.stringify(body);
  }
  if (auth) {
    const current = getBearer();
    if (current !== null) merged.set("Authorization", `Bearer ${current}`);
  }
  return init;
}

async function send(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(path, init);
  } catch (cause) {
    throw networkError(cause);
  }
}

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) throw await parseApiError(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (text === "") return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(response.status, "No se pudo leer la respuesta del servidor.");
  }
}

/**
 * Request the API with the in-memory bearer. A 401 triggers exactly one
 * single-flight refresh and one retry; anything else is parsed into `ApiError`.
 */
export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { auth = true } = options;
  let response = await send(path, buildInit(options));
  if (response.status === 401 && auth) {
    const refreshed = await refreshSession();
    if (refreshed !== null) response = await send(path, buildInit(options));
  }
  return read<T>(response);
}
