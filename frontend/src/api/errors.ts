export type ApiErrorKind =
  | "validation"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "conflict"
  | "rate_limited"
  | "unavailable"
  | "server"
  | "network"
  | "client"
  | "unknown";

export interface FieldError {
  field: string;
  message: string;
}

function kindForStatus(status: number): ApiErrorKind {
  switch (status) {
    case 0:
      return "network";
    case 401:
      return "unauthorized";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 409:
      return "conflict";
    case 422:
      return "validation";
    case 429:
      return "rate_limited";
    case 503:
      return "unavailable";
    default:
      if (status >= 500 && status < 600) return "server";
      if (status >= 400 && status < 500) return "client";
      return "unknown";
  }
}

function genericMessage(kind: ApiErrorKind): string {
  switch (kind) {
    case "network":
      return "No se pudo conectar con el servidor.";
    case "validation":
      return "Revisa los campos del formulario.";
    case "rate_limited":
      return "Demasiados intentos. Inténtalo más tarde.";
    case "server":
    case "unavailable":
      return "Error del servidor. Inténtalo de nuevo más tarde.";
    default:
      return "No se pudo completar la solicitud.";
  }
}

export class ApiError extends Error {
  readonly status: number;
  readonly kind: ApiErrorKind;
  readonly fieldErrors: FieldError[];
  readonly retryAfterSeconds: number | null;

  constructor(
    status: number,
    message: string,
    fieldErrors: FieldError[] = [],
    retryAfterSeconds: number | null = null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.kind = kindForStatus(status);
    this.fieldErrors = fieldErrors;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fieldMessage(item: Record<string, unknown>, message: string): string {
  const ctx = isRecord(item.ctx) ? item.ctx : {};
  switch (item.type) {
    case "missing":
      return "Campo obligatorio";
    case "string_too_short":
      return typeof ctx.min_length === "number" ? `Mínimo ${ctx.min_length} caracteres` : message;
    case "string_too_long":
      return typeof ctx.max_length === "number" ? `Máximo ${ctx.max_length} caracteres` : message;
    case "greater_than_equal":
      return typeof ctx.ge === "number" ? `Debe ser como mínimo ${ctx.ge}` : message;
    case "less_than_equal":
      return typeof ctx.le === "number" ? `Debe ser como máximo ${ctx.le}` : message;
    case "value_error":
      return message.replace(/^Value error, /, "");
    default:
      return message;
  }
}

function parseFields(detail: unknown[]): FieldError[] {
  const fields: FieldError[] = [];
  for (const item of detail) {
    if (!isRecord(item) || typeof item.msg !== "string" || !Array.isArray(item.loc)) continue;
    if (
      !item.loc.every(
        (segment: unknown) => typeof segment === "string" || typeof segment === "number",
      )
    )
      continue;
    const loc = item.loc as (string | number)[];
    const source = loc[0];
    const path =
      typeof source === "string" && ["body", "query", "path", "header", "cookie"].includes(source)
        ? loc.slice(1)
        : loc;
    fields.push({ field: path.join("."), message: fieldMessage(item, item.msg) });
  }
  return fields;
}

export async function parseApiError(response: Response): Promise<ApiError> {
  const status = response.status;
  let message = genericMessage(kindForStatus(status));
  let fieldErrors: FieldError[] = [];
  let retryAfterSeconds: number | null = null;
  try {
    const header = response.headers.get("Retry-After");
    if (header !== null && /^\d+$/.test(header)) {
      const seconds = Number(header);
      if (Number.isSafeInteger(seconds)) retryAfterSeconds = seconds;
    }
    const text = await response.text();
    const body: unknown = JSON.parse(text);
    if (isRecord(body)) {
      // 5xx text is never surfaced: it is English/internal and not meant for end users.
      if (typeof body.detail === "string") {
        if (status < 500 && body.detail.trim() !== "") message = body.detail;
      } else if (status === 422 && Array.isArray(body.detail))
        fieldErrors = parseFields(body.detail);
    }
  } catch {
    // Empty, malformed, or unreadable bodies retain a safe fallback.
  }
  return new ApiError(status, message, fieldErrors, retryAfterSeconds);
}

export function networkError(cause?: unknown): ApiError {
  void cause;
  return new ApiError(0, genericMessage("network"));
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}
