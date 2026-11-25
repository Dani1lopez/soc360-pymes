// Formato de fecha y números para la UI. Las fechas se formatean a mano para
// que el formato sea el esperado en español (dd/mm/aaaa hh:mm) sin depender
// del ICU del entorno donde corran los tests.

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Fecha y hora local en formato dd/mm/aaaa hh:mm. Devuelve "—" si no hay valor. */
export function formatDateTime(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const datePart = [pad(date.getDate()), pad(date.getMonth() + 1), date.getFullYear()].join("/");
  return `${datePart} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Solo la fecha local, dd/mm/aaaa. */
export function formatDate(value: string | null | undefined): string {
  return formatDateTime(value).split(" ")[0] ?? "—";
}

/** Ratio 0..1 como porcentaje redondeado; "Sin datos" cuando es null. */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "Sin datos";
  return `${Math.round(value * 100)} %`;
}

/**
 * Número con separador de millares español. Se formatea a mano para no
 * depender del ICU del entorno (con ICU reducido `Intl` devuelve 1,234).
 */
export function formatCount(value: number): string {
  const [integer = "0", decimals] = Math.abs(value).toString().split(".");
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const sign = value < 0 ? "-" : "";
  return `${sign}${grouped}${decimals === undefined ? "" : `,${decimals}`}`;
}

/** Texto de apoyo para valores opcionales vacíos. */
export function orDash(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : value;
}
