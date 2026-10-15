import type { AssetType, OwnershipMethod } from "@/api/schema";

/** Prefijo reservado del reto, igual que en `app/modules/assets/ownership/verifiers.py`. */
export const CHALLENGE_PREFIX = "_soc360-verify";

function hostOf(value: string): string {
  try {
    return new URL(value).hostname;
  } catch {
    // Un dominio suelto no es una URL; solo hay que quitar el punto final.
    return value.replace(/\.$/, "");
  }
}

/** Registro TXT donde el dueño publica el token. */
export function challengeName(value: string): string {
  return `${CHALLENGE_PREFIX}.${hostOf(value)}`;
}

/** URL del fichero donde el dueño publica el token. */
export function challengeUrl(type: AssetType, value: string): string {
  const origin = type === "web_app" ? new URL(value).origin : `https://${hostOf(value)}`;
  return `${origin}/.well-known/soc360-verify.txt`;
}

/** Reto técnico que admite un tipo de activo; `null` si solo admite declaración. */
export function technicalMethod(type: AssetType): OwnershipMethod | null {
  if (type === "domain" || type === "hostname") return "dns_txt";
  if (type === "web_app") return "http_file";
  return null;
}
