import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { currentUserQueryKey } from "@/features/auth";
import { makeUser } from "@/test/fixtures/auth";
import { server } from "@/test/msw";
import { renderShell } from "@/test/render";
import { UserForm } from "./user-form";

describe("UserForm editing", () => {
  it.each(["admin", "superadmin"] as const)("sends only a changed name for %s", async (role) => {
    const user = makeUser({ role, tenant_id: role === "superadmin" ? null : makeUser().tenant_id });
    const patched = vi.fn();
    const onSaved = vi.fn();
    server.use(
      http.get("*/api/v1/tenants/", () => HttpResponse.json([])),
      http.patch("*/api/v1/users/:id", async ({ request }) => {
        patched(await request.json());
        return HttpResponse.json(user);
      }),
    );
    renderShell(
      <UserForm user={user} caller={user} onSaved={onSaved} onCancel={vi.fn()} />,
      currentUserQueryKey,
      user,
    );
    const save = await screen.findByRole("button", { name: "Guardar cambios" });
    expect(save).toBeDisabled();
    fireEvent.click(save);
    expect(patched).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Nombre completo"), {
      target: { value: "Nuevo nombre" },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(patched).toHaveBeenCalledWith({ full_name: "Nuevo nombre" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });
});
