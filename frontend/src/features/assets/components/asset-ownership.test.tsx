import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OwnershipDeclaration } from "@/api/schema";
import { makeAsset, makeOwnership } from "@/test/fixtures/assets";
import { server } from "@/test/msw";
import { renderWithQueryClient } from "@/test/render";
import { AssetOwnership } from "./asset-ownership";

const ASSET = makeAsset();
const BASE = `*/api/v1/assets/${ASSET.id}/ownership`;
const BLOCKED = "El escaneo está bloqueado hasta declarar la propiedad.";

function useOwnership(
  initial: OwnershipDeclaration[],
  { onDeclare }: { onDeclare?: (method: string) => void } = {},
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
    http.post(`${BASE}/revoke`, () => {
      const revoked = makeOwnership({ status: "revoked", verified_at: null });
      state.items = [revoked];
      return HttpResponse.json(revoked);
    }),
    http.post(BASE, async ({ request }) => {
      const body = (await request.json()) as { method: string };
      onDeclare?.(body.method);
      const created = makeOwnership({
        method: body.method as OwnershipDeclaration["method"],
        status: body.method === "declaration" ? "verified" : "pending",
        verified_at: body.method === "declaration" ? "2026-10-04T12:00:00Z" : null,
      });
      state.items = [created];
      return HttpResponse.json(created, { status: 201 });
    }),
  );
}

beforeEach(() => {
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

  it("declares ownership and reflects the verified state", async () => {
    const declared: string[] = [];
    useOwnership([], { onDeclare: (method) => declared.push(method) });

    renderWithQueryClient(<AssetOwnership asset={ASSET} canWrite />);
    fireEvent.click(await screen.findByRole("button", { name: "Declarar" }));

    expect(await screen.findByText("Verificada")).toBeInTheDocument();
    expect(declared).toEqual(["declaration"]);
    expect(screen.queryByText(BLOCKED)).not.toBeInTheDocument();
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
