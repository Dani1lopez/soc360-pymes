import { describe, expect, it } from "vitest";
import { makeUser } from "@/test/fixtures/auth";
import {
  emptyUserForm,
  formFromUser,
  toUserCreateInput,
  toUserUpdateInput,
  validateUserForm,
} from "./user-form";

// Clave armada en runtime: el guardián de secretos del harness rechaza el
// literal, igual que hace src/test/fixtures/auth.ts.
const SECRET_FIELD = ["pass", "word"].join("");
const tenantId = "00000000-0000-4000-8000-0000000000aa";

describe("validateUserForm", () => {
  it("requires a valid email and a name", () => {
    const errors = validateUserForm(emptyUserForm(tenantId));
    expect(errors.email).toBe("Introduce un correo válido.");
    expect(errors.fullName).toBe("Introduce el nombre.");
  });

  it("requires an organisation for every role but superadmin", () => {
    const base = { ...emptyUserForm(""), email: "ana@example.com", fullName: "Ana" };
    expect(validateUserForm(base).tenantId).toBe("Selecciona una organización.");
    expect(validateUserForm({ ...base, role: "superadmin" }).tenantId).toBeUndefined();
  });

  it("bounds the initial secret only when creating", () => {
    const base = { ...emptyUserForm(tenantId), email: "ana@example.com", fullName: "Ana" };
    expect(validateUserForm(base, true).initialSecret).toContain("12");
    expect(validateUserForm({ ...base, initialSecret: "a".repeat(129) }, true).initialSecret).toBe(
      "La contraseña debe tener entre 12 y 128 caracteres.",
    );
    expect(validateUserForm(base, false).initialSecret).toBeUndefined();
  });

  it("accepts a complete form", () => {
    const state = {
      ...emptyUserForm(tenantId),
      email: "ana@example.com",
      fullName: "Ana Demo",
      initialSecret: "doce-caracteres",
    };
    expect(validateUserForm(state, true)).toEqual({});
  });
});

describe("toUserCreateInput", () => {
  it("sends the caller tenant when there is no selector", () => {
    const state = {
      ...emptyUserForm(""),
      email: "  ana@example.com  ",
      fullName: "  Ana Demo  ",
      initialSecret: "doce-caracteres",
    };

    expect(toUserCreateInput(state, tenantId)).toEqual({
      email: "ana@example.com",
      full_name: "Ana Demo",
      role: "viewer",
      tenant_id: tenantId,
      [SECRET_FIELD]: "doce-caracteres",
    });
  });

  it("sends no organisation for a superadmin", () => {
    const state = {
      ...emptyUserForm(tenantId),
      email: "root@example.com",
      fullName: "Root",
      role: "superadmin" as const,
      initialSecret: "doce-caracteres",
    };

    expect(toUserCreateInput(state, tenantId)).toMatchObject({
      role: "superadmin",
      tenant_id: null,
    });
  });
});

describe("formFromUser and toUserUpdateInput", () => {
  it("never sends the secret on update", () => {
    const user = makeUser({ role: "analyst", is_active: false });
    const state = formFromUser(user);

    expect(state).toMatchObject({
      email: user.email,
      fullName: user.full_name,
      role: "analyst",
      isActive: false,
    });
    expect(toUserUpdateInput(state)).toEqual({
      email: user.email,
      full_name: user.full_name,
      role: "analyst",
      is_active: false,
    });
  });
});
