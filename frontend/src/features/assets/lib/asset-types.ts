import type { AssetType } from "@/api/schema";

// Los seis tipos del backend, en el orden en que se ofrecen en el formulario.
export const ASSET_TYPES = [
  "ip",
  "domain",
  "hostname",
  "web_app",
  "subnet",
  "cloud_resource",
] as const satisfies readonly AssetType[];

const LABELS: Record<AssetType, string> = {
  ip: "Dirección IP",
  domain: "Dominio",
  hostname: "Nombre de host",
  web_app: "Aplicación web",
  subnet: "Subred",
  cloud_resource: "Recurso cloud",
};

/** Ejemplo por tipo: se usa como pista del campo valor. */
const HINTS: Record<AssetType, string> = {
  ip: "Por ejemplo 192.0.2.10 o 2001:db8::1",
  domain: "Por ejemplo acme-corp.example",
  hostname: "Por ejemplo vpn.acme-corp.example",
  web_app: "Debe empezar por http:// o https://",
  subnet: "Notación CIDR, por ejemplo 10.20.30.0/24",
  cloud_resource: "Debe ser un ARN, por ejemplo arn:aws:s3:::mi-bucket",
};

function isAssetType(value: string): value is AssetType {
  return Object.hasOwn(LABELS, value);
}

/** Etiqueta del tipo; un valor fuera del enum no rompe la tabla. */
export function assetTypeLabel(type: string): string {
  return isAssetType(type) ? LABELS[type] : type;
}

export function assetValueHint(type: AssetType): string {
  return HINTS[type];
}

// Mensajes de contrato del backend (`app/modules/assets/service.py`)
// traducidos para el formulario; lo que no esté aquí se muestra tal cual.
const SERVER_MESSAGES: Record<string, string> = {
  "value must be a valid IPv4 or IPv6 address": "Introduce una dirección IP válida.",
  "value must be a valid FQDN": "Introduce un dominio válido, por ejemplo acme-corp.example.",
  "value must be a valid hostname": "Introduce un nombre de host válido.",
  "value must be a valid http(s) URL": "Introduce una URL http:// o https:// válida.",
  "value must be a valid CIDR": "Introduce una subred en notación CIDR.",
  "value must be a valid ARN": "Introduce un ARN válido.",
  "tenant_id mismatch": "El activo debe pertenecer a tu organización.",
  "tenant_id is required": "Selecciona la organización del activo.",
  "tenant not found": "La organización indicada no existe.",
};

export function describeAssetError(message: string): string {
  return SERVER_MESSAGES[message] ?? message;
}
