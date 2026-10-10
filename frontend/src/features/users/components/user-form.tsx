import { useState, type FormEvent } from "react";
import type { Role, UserResponse } from "@/api/schema";
import { FormField } from "@/components/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { roleLabel } from "@/features/auth";
import { useTenants } from "@/features/tenants";
import { errorMessage, fieldError } from "@/lib/errors";
import {
  type UserFormErrors,
  type UserFormState,
  emptyUserForm,
  formFromUser,
  toUserCreateInput,
  toUserUpdateInput,
  validateUserForm,
} from "../lib/user-form";
import { assignableUserRoles } from "../lib/user-roles";
import { useCreateUser, useUpdateUser } from "../hooks/use-user-mutations";

type UserFormProps = {
  /** null al crear; el usuario editado en caso contrario. */
  user: UserResponse | null;
  /** La cuenta que administra; decide organización y roles ofrecidos. */
  caller: UserResponse;
  onSaved: () => void;
  onCancel: () => void;
};

export function UserForm({ user, caller, onSaved, onCancel }: UserFormProps) {
  const isEdit = user !== null;
  const [state, setState] = useState<UserFormState>(() =>
    user === null ? emptyUserForm(caller.tenant_id ?? "") : formFromUser(user),
  );
  const [errors, setErrors] = useState<UserFormErrors>({});
  const tenants = useTenants({ enabled: caller.is_superadmin });
  const create = useCreateUser();
  const update = useUpdateUser();
  const mutation = isEdit ? update : create;
  const roles = assignableUserRoles(caller.role);

  function updateField<K extends keyof UserFormState>(field: K, value: UserFormState[K]) {
    setState((current) => ({ ...current, [field]: value }));
  }

  const serverError = mutation.error !== null ? errorMessage(mutation.error) : null;
  const emailError = errors.email ?? fieldError(mutation.error, "email");
  const nameError = errors.fullName ?? fieldError(mutation.error, "full_name");
  const secretError = errors.initialSecret ?? fieldError(mutation.error, "password");

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mutation.isPending) return;
    const validation = validateUserForm(state, !isEdit);
    setErrors(validation);
    if (Object.keys(validation).length > 0) return;
    if (user === null) {
      create.mutate(toUserCreateInput(state, caller.tenant_id), { onSuccess: onSaved });
    } else {
      update.mutate({ id: user.id, input: toUserUpdateInput(state) }, { onSuccess: onSaved });
    }
  }

  return (
    <section
      aria-labelledby="user-form-heading"
      className="space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 id="user-form-heading" className="text-lg font-semibold">
        {isEdit ? "Editar usuario" : "Nuevo usuario"}
      </h2>
      <form onSubmit={handleSubmit} noValidate className="space-y-4">
        <FormField id="user-email" label="Correo electrónico" error={emailError}>
          <Input
            id="user-email"
            type="email"
            autoComplete="off"
            value={state.email}
            onChange={(event) => updateField("email", event.target.value)}
            aria-invalid={emailError !== undefined ? true : undefined}
            aria-describedby={emailError !== undefined ? "user-email-error" : undefined}
          />
        </FormField>

        <FormField id="user-name" label="Nombre completo" error={nameError}>
          <Input
            id="user-name"
            maxLength={255}
            value={state.fullName}
            onChange={(event) => updateField("fullName", event.target.value)}
            aria-invalid={nameError !== undefined ? true : undefined}
            aria-describedby={nameError !== undefined ? "user-name-error" : undefined}
          />
        </FormField>

        <FormField id="user-role" label="Rol" error={errors.role}>
          <Select
            id="user-role"
            value={state.role}
            onChange={(event) => updateField("role", event.target.value as Role)}
          >
            {roles.map((role) => (
              <option key={role} value={role}>
                {roleLabel(role)}
              </option>
            ))}
          </Select>
        </FormField>

        {!isEdit && caller.is_superadmin && state.role !== "superadmin" && (
          <FormField id="user-tenant" label="Organización" error={errors.tenantId}>
            <Select
              id="user-tenant"
              value={state.tenantId}
              onChange={(event) => updateField("tenantId", event.target.value)}
              aria-invalid={errors.tenantId !== undefined ? true : undefined}
              aria-describedby={errors.tenantId !== undefined ? "user-tenant-error" : undefined}
            >
              <option value="">Selecciona una organización…</option>
              {(tenants.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}
        {!isEdit && state.role === "superadmin" && (
          <p className="text-sm text-muted-foreground">
            Un superadministrador no pertenece a ninguna organización.
          </p>
        )}

        {!isEdit && (
          <FormField
            id="user-secret"
            label="Contraseña inicial"
            hint="Entre 12 y 128 caracteres; se le pedirá cambiarla al entrar."
            error={secretError}
          >
            <Input
              id="user-secret"
              type="password"
              autoComplete="new-password"
              value={state.initialSecret}
              onChange={(event) => updateField("initialSecret", event.target.value)}
              aria-invalid={secretError !== undefined ? true : undefined}
              aria-describedby={secretError !== undefined ? "user-secret-error" : undefined}
            />
          </FormField>
        )}

        {isEdit && (
          <div className="flex items-center gap-2">
            <input
              id="user-active"
              type="checkbox"
              checked={state.isActive}
              onChange={(event) => updateField("isActive", event.target.checked)}
              className="size-4 rounded border-input"
            />
            <label htmlFor="user-active" className="text-sm font-medium">
              Cuenta activa
            </label>
          </div>
        )}

        {serverError !== null && (
          <p role="alert" className="text-sm text-destructive">
            {serverError}
          </p>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Guardando…" : isEdit ? "Guardar cambios" : "Crear usuario"}
          </Button>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancelar
          </Button>
        </div>
      </form>
    </section>
  );
}
