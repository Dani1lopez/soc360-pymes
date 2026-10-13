import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { MetricCard } from "./metric-card";

test("renders an associated label and value with optional hint and icon", () => {
  render(<MetricCard label="Activos" value={12} hint="Último mes" icon={<span>Icon</span>} />);
  expect(screen.getByText("Activos").tagName).toBe("DT");
  expect(screen.getByText("12").tagName).toBe("DD");
  expect(screen.getByText("Último mes")).toHaveClass("text-muted-foreground");
  expect(screen.getByText("Icon")).toBeInTheDocument();
});

test("omits the hint when absent", () => {
  const { container } = render(<MetricCard label="Activos" value="Sin datos" />);
  expect(screen.getByText("Sin datos")).toBeInTheDocument();
  expect(container.querySelector("p")).not.toBeInTheDocument();
});
