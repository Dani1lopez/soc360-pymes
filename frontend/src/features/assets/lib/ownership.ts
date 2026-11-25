import type { AssetType, OwnershipDeclaration, OwnershipMethod } from "@/api/schema";

/** Prefijo reservado del reto, igual que en `app/modules/assets/ownership/verifiers.py`. */
export const CHALLENGE_PREFIX = "_soc360-verify";

/** Copia de la espera propia de S1/H1: una declaración no se verifica, se aprueba. */
export const AWAITING_APPROVAL = "Pendiente de aprobación del superadministrador";

/** `declaration` es la vía para activos sin reto técnico posible. */
export function isHandDeclaration(declaration: OwnershipDeclaration | null): boolean {
  return declaration !== null && declaration.method === "declaration";
}

/**
 * Una declaración hecha a mano nace `pending` y solo un superadministrador la
 * convierte en `verified` (S1/H1); mientras tanto no autoriza ningún escaneo.
 */
export function isAwaitingApproval(declaration: OwnershipDeclaration | null): boolean {
  return (
    declaration !== null && declaration.method === "declaration" && declaration.status === "pending"
  );
}

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
