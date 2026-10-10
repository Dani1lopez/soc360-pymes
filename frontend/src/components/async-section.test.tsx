import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { AsyncSection } from "./async-section";

describe("AsyncSection", () => {
  it("announces loading", () => {
    render(
      <AsyncSection isPending error={null}>
        <p>datos</p>
      </AsyncSection>,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Cargando…");
  });

  it("shows the API message and a retry action", () => {
    const onRetry = vi.fn();
    render(
      <AsyncSection
        isPending={false}
        error={new ApiError(503, "Servicio no disponible.")}
        onRetry={onRetry}
      >
        <p>datos</p>
      </AsyncSection>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Servicio no disponible.");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders an empty state instead of the content", () => {
    render(
      <AsyncSection isEmpty isPending={false} error={null} emptyTitle="No hay activos">
        <p>datos</p>
      </AsyncSection>,
    );
    expect(screen.getByText("No hay activos")).toBeInTheDocument();
    expect(screen.queryByText("datos")).not.toBeInTheDocument();
  });

  it("renders the content and marks background refresh", () => {
    render(
      <AsyncSection isPending={false} isFetching error={null}>
        <p>datos</p>
      </AsyncSection>,
    );
    expect(screen.getByText("datos")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Actualizando…");
  });
});
