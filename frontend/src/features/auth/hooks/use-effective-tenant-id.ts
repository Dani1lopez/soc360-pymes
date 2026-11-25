import { useActiveTenantId } from "@/lib/active-tenant";
import { useCurrentUser } from "./use-current-user";

/**
 * The organization the current user writes to: their own, or for a superadmin
 * (who has none) the one picked in the header switcher. Null means a write
 * cannot be built yet.
 */
export function useEffectiveTenantId(): string | null {
  const { data: user } = useCurrentUser();
  const active = useActiveTenantId();
  if (user === undefined) return null;
  return user.tenant_id ?? (user.is_superadmin ? active : null);
}
