import { describe, expect, it } from "vitest";
import type { Role } from "@/api/schema";
import { ADMIN_ROLES, READ_ROLES, hasAnyRole } from "@/features/auth/roles";

describe("hasAnyRole", () => {
  it.each<[Role, boolean, boolean]>([
    ["viewer", true, false],
    ["analyst", true, false],
    ["ingestor", false, false],
    ["admin", true, true],
    ["superadmin", true, true],
  ])("mirrors the backend allowlists for %s", (role, canRead, canAdmin) => {
    expect(hasAnyRole({ role }, READ_ROLES)).toBe(canRead);
    expect(hasAnyRole({ role }, ADMIN_ROLES)).toBe(canAdmin);
  });

  it("denies a missing user", () => {
    expect(hasAnyRole(null, READ_ROLES)).toBe(false);
    expect(hasAnyRole(undefined, READ_ROLES)).toBe(false);
  });
});
