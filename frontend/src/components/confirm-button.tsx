import { useState } from "react";
import { Button } from "@/components/ui/button";

type ConfirmButtonProps = {
  label: string;
  confirmLabel?: string;
  question?: string;
  onConfirm: () => void;
  disabled?: boolean;
};

/**
 * Acción destructiva en dos pasos, en línea. Evita `window.confirm`, que no se
 * puede probar y bloquea el hilo.
 */
export function ConfirmButton({
  label,
  confirmLabel = "Confirmar",
  question = "¿Seguro?",
  onConfirm,
  disabled = false,
}: ConfirmButtonProps) {
  const [confirming, setConfirming] = useState(false);

  if (!confirming) {
    return (
      <Button variant="outline" size="sm" disabled={disabled} onClick={() => setConfirming(true)}>
        {label}
      </Button>
    );
  }

  return (
    <span
      role="group"
      aria-label={`Confirmar: ${label}`}
      className="inline-flex items-center gap-2"
    >
      <span className="text-sm text-muted-foreground">{question}</span>
      <Button variant="destructive" size="sm" disabled={disabled} onClick={onConfirm}>
        {confirmLabel}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Cancelar
      </Button>
    </span>
  );
}
