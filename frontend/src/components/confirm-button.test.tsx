import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmButton } from "./confirm-button";

describe("ConfirmButton", () => {
  it("asks first and only then calls onConfirm", () => {
    const onConfirm = vi.fn();
    render(<ConfirmButton label="Eliminar" confirmLabel="Dar de baja" onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Dar de baja" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("can be cancelled without confirming", () => {
    const onConfirm = vi.fn();
    render(<ConfirmButton label="Eliminar" onConfirm={onConfirm} />);

    fireEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    expect(onConfirm).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Eliminar" })).toBeInTheDocument();
  });
});
