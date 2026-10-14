import { useSyncExternalStore } from "react";

// The organization a superadmin is working on. A superadmin has no tenant of
// their own, so every write (and the dashboard) needs one picked explicitly.
// Kept in memory only: it is a UI choice, not a credential, and a reload
// simply asks again.

let activeTenantId: string | null = null;
const listeners = new Set<() => void>();

export function getActiveTenantId(): string | null {
  return activeTenantId;
}

export function setActiveTenantId(value: string | null): void {
  if (value === activeTenantId) return;
  activeTenantId = value;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useActiveTenantId(): string | null {
  return useSyncExternalStore(subscribe, getActiveTenantId, getActiveTenantId);
}
