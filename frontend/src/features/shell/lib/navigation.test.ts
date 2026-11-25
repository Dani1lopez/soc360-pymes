import { expect, test } from "vitest";
import { makeUser } from "@/test/fixtures/auth";
import { navigationFor } from "./navigation";

test.each([
  ["viewer", 5],
  ["admin", 7],
  ["ingestor", 0],
] as const)("%s sees %i navigation entries", (role, count) =>
  expect(navigationFor(makeUser({ role }))).toHaveLength(count),
);
