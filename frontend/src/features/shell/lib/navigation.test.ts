import { expect, test } from "vitest";
import { makeUser } from "@/test/fixtures/auth";
import { navigationFor } from "./navigation";

test.each([
  ["viewer", 6],
  ["admin", 7],
] as const)("%s sees %i navigation entries", (role, count) =>
  expect(navigationFor(makeUser({ role }))).toHaveLength(count),
);
