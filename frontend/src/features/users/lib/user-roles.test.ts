import { describe, expect, it } from "vitest";
import { assignableUserRoles } from "./user-roles";

describe("assignableUserRoles", () => {
  it("lets a superadmin create every role", () => {
    expect(assignableUserRoles("superadmin")).toEqual([
      "admin",
      "analyst",
      "viewer",
      "ingestor",
      "superadmin",
    ]);
  });

  it("stops an admin at tenant roles", () => {
    expect(assignableUserRoles("admin")).toEqual(["admin", "analyst", "viewer"]);
  });

  it("offers nothing to a role that cannot reach the page", () => {
    expect(assignableUserRoles("analyst")).toEqual([]);
    expect(assignableUserRoles(undefined)).toEqual([]);
  });
});
