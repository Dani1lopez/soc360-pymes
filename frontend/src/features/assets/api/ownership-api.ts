import { apiFetch } from "@/api/client";
import type { OwnershipDeclaration, OwnershipDeclarationList, OwnershipMethod } from "@/api/schema";

const BASE = "/api/v1/assets";

/** Declaraciones de propiedad de un activo, la más reciente primero. */
export function listOwnership(assetId: string): Promise<OwnershipDeclarationList> {
  return apiFetch<OwnershipDeclarationList>(`${BASE}/${assetId}/ownership`);
}

/** `declaration` autoriza de inmediato; los métodos técnicos abren un reto. */
export function declareOwnership(
  assetId: string,
  method: OwnershipMethod,
): Promise<OwnershipDeclaration> {
  return apiFetch<OwnershipDeclaration>(`${BASE}/${assetId}/ownership`, {
    method: "POST",
    body: { method },
  });
}

/** Ejecuta el reto publicado y, si se cumple, verifica la declaración. */
export function verifyOwnership(assetId: string): Promise<OwnershipDeclaration> {
  return apiFetch<OwnershipDeclaration>(`${BASE}/${assetId}/ownership/verify`, {
    method: "POST",
  });
}

export function revokeOwnership(assetId: string): Promise<OwnershipDeclaration> {
  return apiFetch<OwnershipDeclaration>(`${BASE}/${assetId}/ownership/revoke`, {
    method: "POST",
  });
}
