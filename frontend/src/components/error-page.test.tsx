import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ErrorPage } from "./error-page";

const invalidate = vi.fn();
vi.mock("@tanstack/react-router", () => ({
  useRouter: () => ({ invalidate }),
}));

describe("ErrorPage", () => {
  it("explains the failure and offers a retry", () => {
    render(<ErrorPage />);

    expect(
      screen.getByRole("heading", { name: "No se pudo cargar esta sección" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(invalidate).toHaveBeenCalledTimes(1);
  });

  it("accepts a custom message", () => {
    render(<ErrorPage title="Vaya" message="Concreto" />);
    expect(screen.getByRole("heading", { name: "Vaya" })).toBeInTheDocument();
    expect(screen.getByText("Concreto")).toBeInTheDocument();
  });
});
