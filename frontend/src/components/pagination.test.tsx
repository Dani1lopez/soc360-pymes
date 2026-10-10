import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Pagination } from "./pagination";

describe("Pagination", () => {
  it("describes the visible range", () => {
    render(<Pagination total={26} limit={20} offset={0} onChange={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("Mostrando 1–20 de 26");
  });

  it("disables Anterior on the first page and Siguiente on the last", () => {
    const { rerender } = render(<Pagination total={26} limit={20} offset={0} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();

    rerender(<Pagination total={26} limit={20} offset={20} onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Mostrando 21–26 de 26");
  });

  it("reports the next offset, not a page number", () => {
    const onChange = vi.fn();
    render(<Pagination total={26} limit={20} offset={0} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(onChange).toHaveBeenCalledWith(20);
  });

  it("never returns a negative offset", () => {
    const onChange = vi.fn();
    render(<Pagination total={5} limit={20} offset={20} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(onChange).toHaveBeenCalledWith(0);
  });
});
