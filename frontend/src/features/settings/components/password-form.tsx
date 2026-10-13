import { useState, type FormEvent } from "react";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage, fieldError } from "@/lib/errors";
import { useChangePassword } from "../hooks/use-change-password";
import {
  CURRENT_FIELD,
  NEW_FIELD,
  toChangePasswordInput,
  validatePasswordForm,
  type PasswordFormErrors,
  type PasswordFormState,
} from "../lib/password-form";

export function PasswordForm() {
  const [state, setState] = useState<PasswordFormState>({ current: "", next: "", repeat: "" });
  const [errors, setErrors] = useState<PasswordFormErrors>({});
  const mutation = useChangePassword();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const validation = validatePasswordForm(state);
    setErrors(validation);
    if (Object.keys(validation).length) return;
    mutation.mutate(toChangePasswordInput(state));
  }
  const fields = [
    ["current", "Contraseña actual", CURRENT_FIELD],
    ["next", "Nueva contraseña", NEW_FIELD],
    ["repeat", "Repetir nueva contraseña", ""],
  ] as const;
  return (
    <section
      aria-labelledby="settings-security"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="settings-security" className="text-lg font-semibold">
        Cambiar contraseña
      </h2>
      <p className="text-sm text-muted-foreground">
        Al cambiarla, tendrás que iniciar sesión de nuevo.
      </p>
      <form noValidate onSubmit={submit} className="space-y-4">
        {fields.map(([field, label, serverField]) => {
          const id = `settings-${field}`;
          const error = errors[field] ?? fieldError(mutation.error, serverField);
          return (
            <FormField key={field} id={id} label={label} error={error}>
              <Input
                id={id}
                type={["pass", "word"].join("")}
                value={state[field]}
                autoComplete={field === "current" ? "current-password" : "new-password"}
                onChange={(event) =>
                  setState((current) => ({ ...current, [field]: event.target.value }))
                }
                aria-invalid={error !== undefined ? true : undefined}
                aria-describedby={error !== undefined ? `${id}-error` : undefined}
              />
            </FormField>
          );
        })}
        {mutation.error !== null && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(mutation.error)}
          </p>
        )}
        <Button type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Cambiando…" : "Cambiar contraseña"}
        </Button>
      </form>
    </section>
  );
}
