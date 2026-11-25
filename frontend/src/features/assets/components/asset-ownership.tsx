import { isApiError } from "@/api/errors";
import type { ApiErrorKind } from "@/api/errors";
import type { AssetResponse, OwnershipDeclaration } from "@/api/schema";
import { ConfirmButton } from "@/components/confirm-button";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/features/auth";
import { errorMessage } from "@/lib/errors";
import {
  useApproveOwnership,
  useDeclareOwnership,
  useOwnership,
  useRevokeOwnership,
  useVerifyOwnership,
} from "../hooks/use-ownership";
import {
  AWAITING_APPROVAL,
  challengeName,
  challengeUrl,
  isAwaitingApproval,
  isHandDeclaration,
  technicalMethod,
} from "../lib/ownership";

const BLOCKED = "El escaneo está bloqueado hasta declarar la propiedad.";
const APPROVE_FALLBACK = "No se pudo aprobar la declaración.";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pendiente",
  verified: "Verificada",
  revoked: "Revocada",
  failed: "Fallida",
};

/**
 * El backend responde en inglés; las tres respuestas que el usuario puede
 * provocar desde aquí tienen su propia copia (409, 404 y 403).
 */
const APPROVE_ERRORS: Partial<Record<ApiErrorKind, string>> = {
  conflict: "Solo una declaración pendiente hecha a mano se puede aprobar.",
  not_found: "Ya no hay una declaración pendiente de aprobación.",
  forbidden: "Solo el superadministrador puede aprobar la declaración.",
};

function statusLabel(declaration: OwnershipDeclaration | null): string {
  if (declaration === null) return "Sin declarar";
  if (isAwaitingApproval(declaration)) return AWAITING_APPROVAL;
  return STATUS_LABELS[declaration.status] ?? declaration.status;
}

function approveErrorMessage(error: unknown): string {
  if (!isApiError(error)) return APPROVE_FALLBACK;
  return APPROVE_ERRORS[error.kind] ?? errorMessage(error, APPROVE_FALLBACK);
}

type AssetOwnershipProps = {
  asset: AssetResponse;
  /** El backend decide igual; aquí solo se oculta lo que devolvería 403. */
  canWrite: boolean;
};

/**
 * Estado de propiedad de un activo y sus acciones: declarar, publicar el reto
 * técnico, verificarlo, aprobarlo (solo superadministrador) y revocar. Una
 * consulta por fila es aceptable para el tamaño de página (20); un endpoint por
 * lote sería el siguiente paso.
 */
export function AssetOwnership({ asset, canWrite }: AssetOwnershipProps) {
  const { data: user } = useCurrentUser();
  const query = useOwnership(asset.id);
  const declare = useDeclareOwnership(asset.id);
  const verify = useVerifyOwnership(asset.id);
  const approve = useApproveOwnership(asset.id);
  const revoke = useRevokeOwnership(asset.id);

  const current = query.data?.items[0] ?? null;
  const busy = declare.isPending || verify.isPending || approve.isPending || revoke.isPending;
  const error = declare.error ?? verify.error ?? approve.error ?? revoke.error;
  const verified = current?.status === "verified";
  const awaiting = current?.status === "pending";
  // Aprobar es decisión del superadministrador: un admin de tenant no la ve.
  const canApprove = user?.role === "superadmin" && isAwaitingApproval(current);
  const challenge = awaiting && !isHandDeclaration(current);
  const method = technicalMethod(asset.type);

  return (
    <div className="space-y-1">
      <span className="text-sm font-medium">{statusLabel(current)}</span>
      {!verified && <p className="text-xs text-muted-foreground">{BLOCKED}</p>}

      {challenge && current !== null && (
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
          {canApprove && (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => approve.mutate()}>
              Aprobar
            </Button>
          )}
          {challenge && (
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
          {approve.error !== null
            ? approveErrorMessage(approve.error)
            : errorMessage(error, "No se pudo actualizar la declaración.")}
        </p>
      )}
    </div>
  );
}
