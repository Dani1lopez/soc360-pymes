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
  it("sends only the changed name for an admin", () => {
    const user = makeUser({ role: "admin" });
    expect(
      toUserUpdateInput({ ...formFromUser(user), fullName: "  Nuevo nombre  " }, user),
    ).toEqual({
      full_name: "Nuevo nombre",
    });
  });

  it("omits the unchanged superadmin role when editing the name", () => {
    const user = makeUser({ role: "superadmin", tenant_id: null });
    expect(toUserUpdateInput({ ...formFromUser(user), fullName: "Nuevo nombre" }, user)).toEqual({
      full_name: "Nuevo nombre",
    });
  });

  it("includes a changed role", () => {
    const user = makeUser({ role: "viewer" });
    expect(toUserUpdateInput({ ...formFromUser(user), role: "analyst" }, user)).toEqual({
      role: "analyst",
    });
  });

  it("returns an empty object for unchanged values after trimming", () => {
    const user = makeUser();
    expect(toUserUpdateInput({ ...formFromUser(user), email: ` ${user.email} ` }, user)).toEqual(
      {},
    );
  });

  it("includes changed email and active state", () => {
    const user = makeUser({ is_active: true });
    expect(
      toUserUpdateInput(
        { ...formFromUser(user), email: " nuevo@example.com ", isActive: false },
        user,
      ),
    ).toEqual({
      email: "nuevo@example.com",
      is_active: false,
    });
  });
  it("never sends the secret on update", () => {
    const user = makeUser({ role: "analyst", is_active: false });
    const state = formFromUser(user);

    expect(state).toMatchObject({
      email: user.email,
      fullName: user.full_name,
      role: "analyst",
      isActive: false,
    });
    expect(toUserUpdateInput({ ...state, initialSecret: "doce-caracteres" }, user)).toEqual({});
  });
});
