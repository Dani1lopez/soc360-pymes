import type { AssetResponse, OwnershipDeclaration } from "@/api/schema";
import { ConfirmButton } from "@/components/confirm-button";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";
import {
  useDeclareOwnership,
  useOwnership,
  useRevokeOwnership,
  useVerifyOwnership,
} from "../hooks/use-ownership";
import { challengeName, challengeUrl, technicalMethod } from "../lib/ownership";

const BLOCKED = "El escaneo está bloqueado hasta declarar la propiedad.";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pendiente",
  verified: "Verificada",
  revoked: "Revocada",
  failed: "Fallida",
};

function statusLabel(declaration: OwnershipDeclaration | null): string {
  if (declaration === null) return "Sin declarar";
  return STATUS_LABELS[declaration.status] ?? declaration.status;
}

type AssetOwnershipProps = {
  asset: AssetResponse;
  /** El backend decide igual; aquí solo se oculta lo que devolvería 403. */
  canWrite: boolean;
};

/**
 * Estado de propiedad de un activo y sus acciones: declarar, publicar el reto
 * técnico, verificarlo y revocar. Una consulta por fila es aceptable para el
 * tamaño de página (20); un endpoint por lote sería el siguiente paso.
 */
export function AssetOwnership({ asset, canWrite }: AssetOwnershipProps) {
  const query = useOwnership(asset.id);
  const declare = useDeclareOwnership(asset.id);
  const verify = useVerifyOwnership(asset.id);
  const revoke = useRevokeOwnership(asset.id);

  const current = query.data?.items[0] ?? null;
  const busy = declare.isPending || verify.isPending || revoke.isPending;
  const error = declare.error ?? verify.error ?? revoke.error;
  const verified = current?.status === "verified";
  const awaiting = current?.status === "pending";
  const method = technicalMethod(asset.type);

  return (
    <div className="space-y-1">
      <span className="text-sm font-medium">{statusLabel(current)}</span>
      {!verified && <p className="text-xs text-muted-foreground">{BLOCKED}</p>}

      {awaiting && current !== null && (
        <p className="text-xs text-muted-foreground">
          Publica <code className="font-mono">{current.token}</code> en{" "}
          <code className="font-mono">
            {current.method === "dns_txt"
              ? challengeName(asset.value)
              : challengeUrl(asset.type, asset.value)}
          </code>
        </p>
      )}

      {canWrite && (
        <div className="flex flex-wrap items-center gap-2">
          {!verified && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => declare.mutate("declaration")}
            >
              Declarar
            </Button>
          )}
          {!verified && !awaiting && method !== null && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => declare.mutate(method)}
            >
              {method === "dns_txt" ? "Reto DNS" : "Reto web"}
            </Button>
          )}
          {awaiting && (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => verify.mutate()}>
              Verificar
            </Button>
          )}
          {current !== null && current.status !== "revoked" && (
            <ConfirmButton
              label="Revocar"
              confirmLabel="Confirmar revocación"
              question="¿Revocar la declaración?"
              disabled={busy}
              onConfirm={() => revoke.mutate()}
            />
          )}
        </div>
      )}

      {error !== null && (
        <p role="alert" className="text-xs text-destructive">
          {errorMessage(error, "No se pudo actualizar la declaración.")}
        </p>
      )}
    </div>
  );
}
