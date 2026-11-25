import type { AssetType } from "@/api/schema";

// Validación de forma en el cliente, alineada con
// `app/modules/assets/service.py::_validate_asset_value`. La autoridad sigue
// siendo el backend: esto solo evita ida y vuelta para errores evidentes.

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const FQDN = /^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$/;
const HOSTNAME =
  /^(?=.{1,253}$)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/;
const ARN = /^arn:[^:]+:[^:]+:[^:]*:[^:]*:.+$/;

function isIpv4(value: string): boolean {
  const match = IPV4.exec(value);
  if (match === null) return false;
  return match.slice(1).every((part) => Number(part) <= 255);
}

function isIpv6(value: string): boolean {
  if (!value.includes(":")) return false;
  const [head, tail] = value.split("::") as [string, string?];
  if (value.split("::").length > 2) return false;
  const groups = (group: string) => (group === "" ? [] : group.split(":"));
  const headGroups = groups(head);
  const tailGroups = groups(tail ?? "");
  if (tail === undefined && headGroups.length !== 8) return false;
  if (tail !== undefined && headGroups.length + tailGroups.length > 7) return false;
  return [...headGroups, ...tailGroups].every((group) => /^[0-9a-fA-F]{1,4}$/.test(group));
}

function isSubnet(value: string): boolean {
  const [address, prefix] = value.split("/") as [string, string?];
  if (address === undefined || prefix === undefined) return false;
  if (!/^\d{1,3}$/.test(prefix)) return false;
  const bits = Number(prefix);
  if (isIpv4(address)) return bits <= 32;
  if (isIpv6(address)) return bits <= 128;
  return false;
}

function isWebApp(value: string): boolean {
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  return url.protocol === "http:" || url.protocol === "https:";
}

function isValidValue(type: AssetType, value: string): boolean {
  switch (type) {
    case "ip":
      return isIpv4(value) || isIpv6(value);
    case "domain":
      return FQDN.test(value);
    case "hostname":
      return HOSTNAME.test(value);
    case "web_app":
      return isWebApp(value);
    case "subnet":
      return isSubnet(value);
    case "cloud_resource":
      return ARN.test(value);
  }
}

const MESSAGES: Record<"empty" | "value", string> = {
  empty: "Introduce un valor.",
  value: "El valor no es válido para el tipo seleccionado.",
};

/** Error de validación del par tipo/valor, o null si el formulario es válido. */
export function validateAssetValue(type: AssetType, rawValue: string): string | null {
  const value = rawValue.trim();
  if (value === "") return MESSAGES.empty;
  if (value.length > 255) return "El valor no puede superar 255 caracteres.";
  if (!isValidValue(type, value)) return MESSAGES.value;
  return null;
}
