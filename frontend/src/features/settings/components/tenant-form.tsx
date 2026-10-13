import { useState, type FormEvent } from "react";
import { LockKeyhole, CheckCircle2 } from "lucide-react";
import type { TenantResponse, TenantUpdateInput } from "@/api/schema";
import { FormField } from "@/components/form-field";
import { SEVERITY_LABELS } from "@/components/severity-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { errorMessage, fieldError } from "@/lib/errors";
import { formatDateTime } from "@/lib/format";
import {
  formFromTenant,
  PLANS,
  toTenantUpdateInput,
  validateTenantForm,
  type TenantFormErrors,
  type TenantFormState,
} from "../lib/tenant-form";

type Props = {
  tenant: TenantResponse;
  canEdit: boolean;
  isPending: boolean;
  error: unknown;
  saved: boolean;
  onSave: (input: TenantUpdateInput) => void;
};

export function TenantForm({ tenant, canEdit, isPending, error, saved, onSave }: Props) {
  const [draft, setDraft] = useState<TenantFormState | null>(null);
  const [errors, setErrors] = useState<TenantFormErrors>({});
  const state = draft ?? formFromTenant(tenant);
  function update<K extends keyof TenantFormState>(field: K, value: TenantFormState[K]) {
    setDraft({ ...state, [field]: value });
  }
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canEdit || isPending) return;
    const validation = validateTenantForm(state);
    setErrors(validation);
    if (Object.keys(validation).length) return;
    onSave(toTenantUpdateInput(state, tenant));
  }
  const textFields = [
    ["name", "Nombre", "text"],
    ["max_assets", "Máximo de activos", "number"],
    ["timezone", "Zona horaria", "text"],
    ["scan_schedule", "Programación de escaneos", "text"],
    ["notification_email", "Correo de notificaciones", "email"],
    ["daily_max", "Límite diario", "number"],
    ["concurrent_max", "Límite concurrente", "number"],
  ] as const;
  function fieldProps(field: keyof TenantFormState, serverField = field as string) {
    const message = errors[field] ?? fieldError(error, serverField);
    const id = `tenant-${field}`;
    return {
      id,
      message,
      "aria-invalid": message !== undefined ? true : undefined,
      "aria-describedby": message !== undefined ? `${id}-error` : undefined,
    };
  }
  const plan = fieldProps("plan");
  const severity = fieldProps("severity_threshold", "settings.severity_threshold");
  return (
    <section
      aria-labelledby="settings-organization"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="settings-organization" className="text-lg font-semibold">
        Configuración de la organización
      </h2>
      <p className="text-sm text-muted-foreground">
        Actualizada: {formatDateTime(tenant.updated_at)}
      </p>
      {!canEdit && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <LockKeyhole aria-hidden="true" className="size-4" />
          Solo un superadministrador puede modificar la configuración de la organización
        </p>
      )}
      <form noValidate onSubmit={submit} className="space-y-4">
        {textFields.map(([field, label, type]) => {
          const serverField =
            field === "daily_max" || field === "concurrent_max"
              ? `settings.scan_limits.${field}`
              : ["timezone", "scan_schedule", "notification_email"].includes(field)
                ? `settings.${field}`
                : field;
          const props = fieldProps(field, serverField);
          return (
            <FormField key={field} id={props.id} label={label} error={props.message}>
              <Input
                id={props.id}
                type={type}
                min={type === "number" ? 1 : undefined}
                readOnly={!canEdit}
                disabled={isPending}
                value={state[field]}
                onChange={(event) => update(field, event.target.value)}
                aria-invalid={props["aria-invalid"]}
                aria-describedby={props["aria-describedby"]}
              />
            </FormField>
          );
        })}
        <FormField id={plan.id} label="Plan" error={plan.message}>
          <Select
            id={plan.id}
            disabled={!canEdit || isPending}
            value={state.plan}
            onChange={(event) => update("plan", event.target.value)}
            aria-invalid={plan["aria-invalid"]}
            aria-describedby={plan["aria-describedby"]}
          >
            {!PLANS.some((item) => item === state.plan) && (
              <option value={state.plan}>{state.plan}</option>
            )}
            {PLANS.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField id={severity.id} label="Umbral de severidad" error={severity.message}>
          <Select
            id={severity.id}
            disabled={!canEdit || isPending}
            value={state.severity_threshold}
            onChange={(event) =>
              update(
                "severity_threshold",
                event.target.value as TenantFormState["severity_threshold"],
              )
            }
            aria-invalid={severity["aria-invalid"]}
            aria-describedby={severity["aria-describedby"]}
          >
            {(["critical", "high", "medium", "low"] as const).map((item) => (
              <option key={item} value={item}>
                {SEVERITY_LABELS[item]}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField id="tenant-is_active" label="Organización activa">
          <Input
            id="tenant-is_active"
            type="checkbox"
            className="size-4"
            checked={state.is_active}
            disabled={!canEdit || isPending}
            onChange={(event) => update("is_active", event.target.checked)}
          />
        </FormField>
        {error !== null && error !== undefined && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(error)}
          </p>
        )}
        {saved && (
          <p role="status" className="flex items-center gap-2 text-sm">
            <CheckCircle2 aria-hidden="true" className="size-4" />
            Configuración guardada.
          </p>
        )}
        {canEdit && (
          <Button type="submit" disabled={isPending}>
            {isPending ? "Guardando…" : "Guardar configuración"}
          </Button>
        )}
      </form>
    </section>
  );
}
