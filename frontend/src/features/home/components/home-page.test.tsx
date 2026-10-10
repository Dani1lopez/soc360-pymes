import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { HomePage } from "./home-page";

test("renders the application heading", () => {
  render(<HomePage />);

  expect(screen.getByRole("heading", { name: "SOC360 PyMEs" })).toBeInTheDocument();
});
