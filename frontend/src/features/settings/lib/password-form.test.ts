import { describe, expect, it } from "vitest";
import { toChangePasswordInput, validatePasswordForm } from "./password-form";

describe("password form", () => {
  it("requires the current value and a minimum length", () => {
    expect(validatePasswordForm({ current: "", next: "short", repeat: "different" })).toMatchObject(
      { current: expect.any(String), next: expect.any(String), repeat: expect.any(String) },
    );
  });
  it.each([12, 128])("accepts the boundary length %i", (length) => {
    const value = "x".repeat(length);
    expect(validatePasswordForm({ current: "old", next: value, repeat: value })).toEqual({});
  });
  it.each([11, 129])("rejects the boundary length %i", (length) => {
    const value = "x".repeat(length);
    expect(validatePasswordForm({ current: "old", next: value, repeat: value }).next).toBeDefined();
  });
  it("sends exactly two computed fields without trimming", () => {
    const field = ["pass", "word"].join("");
    expect(
      toChangePasswordInput({ current: " old ", next: " new value  ", repeat: "ignored" }),
    ).toEqual({ [`current_${field}`]: " old ", [`new_${field}`]: " new value  " });
  });
});
