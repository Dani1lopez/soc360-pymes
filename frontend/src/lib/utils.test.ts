import { expect, test } from "vitest";
import { cn } from "@/lib/utils";

test("merges conflicting Tailwind classes", () => {
  expect(cn("px-2", "px-4")).toBe("px-4");
});

test("supports conditional classes and preserves unrelated utilities", () => {
  expect(cn("flex px-2", false, { "px-4": true })).toBe("flex px-4");
});
