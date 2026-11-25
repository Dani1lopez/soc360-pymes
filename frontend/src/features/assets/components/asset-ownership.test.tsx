import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OwnershipDeclaration, Role } from "@/api/schema";
import { makeUser } from "@/test/fixtures/auth";
import { makeAsset, makeOwnership } from "@/test/fixtures/assets";
import { server } from "@/test/msw";
import { renderWithQueryClient } from "@/test/render";
import { AssetOwnership } from "./asset-ownership";

const ASSET = makeAsset();
const BASE = `*/api/v1/assets/${ASSET.id}/ownership`;
const BLOCKED = "El escaneo está bloqueado hasta declarar la propiedad.";
const AWAITING = "Pendiente de aprobación del superadministrador";

function useUser(role: Role = "admin") {
  server.use(
    http.get("*/api/v1/users/me", () =>
      HttpResponse.json(makeUser({ role, is_superadmin: role === "superadmin" })),
    ),
  );
}

function useOwnership(
  initial: OwnershipDeclaration[],
  { onDeclare, onApprove }: { onDeclare?: (method: string) => void; onApprove?: () => void } = {},
) {
  // El GET tiene que reflejar lo que devuelve cada POST: la mutación invalida
  // la consulta y la UI se relee.
  const state = { items: initial };
  server.use(
    http.get(BASE, () => HttpResponse.json({ items: state.items, total: state.items.length })),
    http.post(`${BASE}/verify`, () => {
      const verified = makeOwnership({
        status: "verified",
        verified_at: "2026-10-04T12:00:00Z",
      });
      state.items = [verified];
      return HttpResponse.json(verified);
    }),
    http.post(`${BASE}/approve`, () => {
      onApprove?.();
      const approved = makeOwnership({
        status: "verified",
        verified_at: "2026-10-04T12:00:00Z",
        approved_by_user_id: makeUser({ role: "superadmin" }).id,
      });
      state.items = [approved];
      return HttpResponse.json(approved);
    }),
    http.post(`${BASE}/revoke`, () => {
      const revoked = makeOwnership({ status: "revoked", verified_at: null });
      state.items = [revoked];
      return HttpResponse.json(revoked);
    }),
    http.post(BASE, async ({ request }) => {
      const body = (await request.json()) as { method: string };
      onDeclare?.(body.method);
      // S1/H1: toda declaración nace pendiente, incluida la hecha a mano.
      const created = makeOwnership({
        method: body.method as OwnershipDeclaration["method"],
        status: "pending",
        verified_at: null,
      });
      state.items = [created];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
}

function pendingDeclaration(): OwnershipDeclaration {
  return makeOwnership({ method: "declaration", status: "pending", verified_at: null });
}

beforeEach(() => {
  // Rol por defecto: un admin de tenant, que nunca aprueba.
  useUser();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("AssetOwnership", () => {
  it("shows an undeclared asset with the scan warning", async () => {
    useOwnership([]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);

    expect(await screen.findByText("Sin declarar")).toBeInTheDocument();
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Declarar" })).toBeInTheDocument();
  });

  it("declares ownership and waits for superadmin approval", async () => {
    const declared: string[] = [];
    useOwnership([], { onDeclare: (method) => declared.push(method) });

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Declarar" }));

    expect(await screen.findByText(AWAITING)).toBeInTheDocument();
    expect(declared).toEqual(["declaration"]);
    // Una declaración hecha a mano no se verifica publicando un reto.
    expect(screen.queryByRole("button", { name: "Verificar" })).not.toBeInTheDocument();
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
  });

  it("lets a superadmin approve the pending declaration", async () => {
    useUser("superadmin");
    const approved = vi.fn();
    useOwnership([pendingDeclaration()], { onApprove: approved });

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    expect(await screen.findByText(AWAITING)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Aprobar" }));

    expect(await screen.findByText("Verificada")).toBeInTheDocument();
    expect(approved).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(BLOCKED)).not.toBeInTheDocument();
  });

  it("does not offer approval to a tenant admin", async () => {
    useOwnership([pendingDeclaration()]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);

    expect(await screen.findByText(AWAITING)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aprobar" })).not.toBeInTheDocument();
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
  });

  it("does not offer approval for a technical challenge", async () => {
    useUser("superadmin");
    useOwnership([makeOwnership({ method: "dns_txt", status: "pending", verified_at: null })]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);

    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aprobar" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Verificar" })).toBeInTheDocument();
  });

  it("shows an error when the approval conflicts", async () => {
    useUser("superadmin");
    useOwnership([pendingDeclaration()]);
    // Se registra después de los handlers base: el último gana.
    server.use(
      http.post(`${BASE}/approve`, () =>
        HttpResponse.json({ detail: "ownership declaration cannot be approved" }, { status: 409 }),
      ),
    );

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Solo una declaración pendiente hecha a mano se puede aprobar.",
    );
  });

  it("verifies a pending challenge", async () => {
    useOwnership([makeOwnership({ method: "dns_txt", status: "pending", verified_at: null })]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Verificar" }));

    expect(await screen.findByText("Verificada")).toBeInTheDocument();
  });

  it("keeps the token visible while a challenge is pending", async () => {
    useOwnership([
      makeOwnership({
        method: "dns_txt",
        status: "pending",
        verified_at: null,
        token: "challenge-token",
      }),
    ]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);

    expect(await screen.findByText(/challenge-token/)).toBeInTheDocument();
    expect(screen.getByText(/_soc360-verify\.acme-corp\.example/)).toBeInTheDocument();
  });

  it("revokes only after the second step", async () => {
    useOwnership([makeOwnership()]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Revocar" }));
    expect(screen.getByText("¿Revocar la declaración?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Confirmar revocación" }));

    await waitFor(() => expect(screen.getByText("Revocada")).toBeInTheDocument());
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
  });

  it("publishes a technical challenge instead of self-declaring", async () => {
    const declared: string[] = [];
    useOwnership([], { onDeclare: (method) => declared.push(method) });

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Reto DNS" }));

    expect(await screen.findByText("Pendiente")).toBeInTheDocument();
    expect(declared).toEqual(["dns_txt"]);
    expect(screen.getByText(BLOCKED)).toBeInTheDocument();
  });

  it("shows the state to a reader without offering actions", async () => {
    useOwnership([makeOwnership()]);

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite={false} />);

    expect(await screen.findByText("Verificada")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revocar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Declarar" })).not.toBeInTheDocument();
  });
});
