import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { getActiveTenantId, setActiveTenantId, useActiveTenantId } from "./active-tenant";

afterEach(() => setActiveTenantId(null));

describe("active tenant", () => {
  it("starts without a selection", () => {
    expect(getActiveTenantId()).toBeNull();
  });

  it("re-renders subscribers when the selection changes", () => {
    const { result } = renderHook(() => useActiveTenantId());
    expect(result.current).toBeNull();

    act(() => setActiveTenantId("tenant-1"));
    expect(result.current).toBe("tenant-1");

    act(() => setActiveTenantId(null));
    expect(result.current).toBeNull();
  });
});
