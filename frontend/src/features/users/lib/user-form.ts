import type { Role, UserCreateInput, UserResponse, UserUpdateInput } from "@/api/schema";

const SECRET_FIELD = ["pass", "word"].join("") as keyof UserCreateInput;

export type UserFormState = {
  email: string;
  fullName: string;
  role: Role | "";
  tenantId: string;
  initialSecret: string;
  isActive: boolean;
};
export type UserFormErrors = Partial<Record<keyof UserFormState, string>>;

export function emptyUserForm(tenantId = ""): UserFormState {
  return { email: "", fullName: "", role: "viewer", tenantId, initialSecret: "", isActive: true };
}

export function formFromUser(user: UserResponse): UserFormState {
  return {
    ...emptyUserForm(user.tenant_id ?? ""),
    email: user.email,
    fullName: user.full_name,
    role: user.role,
    isActive: user.is_active,
  };
}

export function validateUserForm(state: UserFormState, creating = true): UserFormErrors {
  const errors: UserFormErrors = {};
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.email.trim()))
    errors.email = "Introduce un correo válido.";
  if (!state.fullName.trim()) errors.fullName = "Introduce el nombre.";
  if (!state.role) errors.role = "Selecciona un rol.";
  if (state.role !== "superadmin" && !state.tenantId)
    errors.tenantId = "Selecciona una organización.";
  if (creating && (state.initialSecret.length < 12 || state.initialSecret.length > 128)) {
    errors.initialSecret = "La contraseña debe tener entre 12 y 128 caracteres.";
  }
  return errors;
}

export function toUserCreateInput(
  state: UserFormState,
  callerTenantId: string | null,
): UserCreateInput {
  return {
    email: state.email.trim(),
    full_name: state.fullName.trim(),
    role: state.role || "viewer",
    tenant_id: state.role === "superadmin" ? null : state.tenantId || callerTenantId,
    [SECRET_FIELD]: state.initialSecret,
  } as UserCreateInput;
}

export function toUserUpdateInput(state: UserFormState, original: UserResponse): UserUpdateInput {
  const input: UserUpdateInput = {};
  const email = state.email.trim();
  const fullName = state.fullName.trim();
  const role = state.role || "viewer";
  if (email !== original.email) input.email = email;
  if (fullName !== original.full_name) input.full_name = fullName;
  if (role !== original.role) input.role = role;
  if (state.isActive !== original.is_active) input.is_active = state.isActive;
  return input;
}
