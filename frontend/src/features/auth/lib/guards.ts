import { redirect } from "@tanstack/react-router";
import type { Role, UserResponse } from "@/api/schema";
import { hasAnyRole } from "./roles";

const FALLBACK = "/";

/**
 * Keep a post-login destination only when it stays on this origin. The value is
 * resolved the way the browser would (stripping tabs/newlines, treating `\` as
 * `/`), so prefix tricks such as `/\t/evil.com` cannot become `//evil.com`.
 * The normalized path is checked too: `/a/..//evil.com` resolves to the path
 * `//evil.com`, which would leave the origin once used as an href.
 */
export function sanitizeRedirect(value: unknown): string {
  if (typeof value !== "string" || !value.startsWith("/")) return FALLBACK;
  let target: URL;
  try {
    target = new URL(value, window.location.origin);
  } catch {
    return FALLBACK;
  }
  if (
    target.origin !== window.location.origin ||
    target.pathname.startsWith("//") ||
    target.pathname.startsWith("/login")
  ) {
    return FALLBACK;
  }
  return `${target.pathname}${target.search}${target.hash}`;
}

export function requireRoles(
  user: Pick<UserResponse, "role"> | null | undefined,
  allowed: readonly Role[],
): void {
  if (!hasAnyRole(user, allowed)) throw redirect({ to: "/forbidden" });
}
