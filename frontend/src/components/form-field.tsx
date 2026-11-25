import type { ReactNode } from "react";

type FormFieldProps = {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: ReactNode;
};

/**
 * Campo de formulario: etiqueta asociada, control y mensaje de error ligado al
 * input por `aria-describedby` (el control pasa el id `<id>-error`).
 */
export function FormField({ id, label, error, hint, children }: FormFieldProps) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {hint !== undefined && !error && <p className="text-xs text-muted-foreground">{hint}</p>}
      {error !== undefined && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
