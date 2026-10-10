import { expect, test } from "vitest";
import { sanitizeRedirect, requireRoles } from "./guards";
import { ADMIN_ROLES } from "./roles";
import { makeUser } from "./test-fixtures";

test.each([
  "//evil.com",
  "/\\evil.com",
  "/\t/evil.com",
  "/\n/evil.com",
  "/\\/evil.com",
  "/a/..//evil.com",
  "/a/../\\evil.com",
  "https://evil.com",
  "javascript:alert(1)",
  "",
  42,
  undefined,
  "/login?redirect=/x",
])("rejects unsafe redirect %s", (value) => {
  expect(sanitizeRedirect(value)).toBe("/");
});
test("preserves a local target", () => {
  expect(sanitizeRedirect("/assets?x=1#top")).toBe("/assets?x=1#top");
});
test("denies viewer access to admin routes", () => {
  expect(() => requireRoles(makeUser({ role: "viewer" }), ADMIN_ROLES)).toThrow();
});
test("allows admin access", () => {
  expect(() => requireRoles(makeUser({ role: "admin" }), ADMIN_ROLES)).not.toThrow();
});
