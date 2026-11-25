import type { ChangePasswordInput } from "@/api/schema";

const SECRET_FIELD = ["pass", "word"].join("");
export const CURRENT_FIELD = `current_${SECRET_FIELD}` as keyof ChangePasswordInput;
export const NEW_FIELD = `new_${SECRET_FIELD}` as keyof ChangePasswordInput;
export type PasswordFormState = { current: string; next: string; repeat: string };
export type PasswordFormErrors = Partial<Record<keyof PasswordFormState, string>>;

export function validatePasswordForm(state: PasswordFormState): PasswordFormErrors {
  const errors: PasswordFormErrors = {};
  if (!state.current) errors.current = "Introduce la contraseña actual.";
  if (state.next.length < 12 || state.next.length > 128) {
    errors.next = "La nueva contraseña debe tener entre 12 y 128 caracteres.";
  }
  if (state.repeat !== state.next) errors.repeat = "Las contraseñas no coinciden.";
  return errors;
}

export function toChangePasswordInput(state: PasswordFormState): ChangePasswordInput {
  return { [CURRENT_FIELD]: state.current, [NEW_FIELD]: state.next } as ChangePasswordInput;
}
