import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/errors";

type AsyncSectionProps = {
  isPending: boolean;
  isFetching?: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyMessage?: string;
  onRetry?: () => void;
  children: ReactNode;
};

/**
 * Envuelve el contenido de una consulta y resuelve sus cuatro estados:
 * carga, error (con reintento), vacío y datos. Evita repetir la misma
 * cascada en cada página con datos.
 */
export function AsyncSection({
  isPending,
  isFetching = false,
  error,
  isEmpty = false,
  emptyTitle = "Sin resultados",
  emptyMessage = "Todavía no hay nada que mostrar.",
  onRetry,
  children,
}: AsyncSectionProps) {
  if (isPending) {
    return (
      <p
        role="status"
        className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground"
      >
        Cargando…
      </p>
    );
  }

  if (error) {
    return (
      <div role="alert" className="space-y-3 rounded-lg border border-destructive/40 bg-card p-6">
        <p className="text-sm font-medium">No se pudieron cargar los datos</p>
        <p className="text-sm text-muted-foreground">{errorMessage(error)}</p>
        {onRetry !== undefined && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Reintentar
          </Button>
        )}
      </div>
    );
  }

  if (isEmpty) {
    return (
      <div className="space-y-1 rounded-lg border border-border bg-card p-6">
        <p className="text-sm font-medium">{emptyTitle}</p>
        <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {isFetching && (
        <p role="status" className="text-xs text-muted-foreground">
          Actualizando…
        </p>
      )}
      {children}
    </div>
  );
}
