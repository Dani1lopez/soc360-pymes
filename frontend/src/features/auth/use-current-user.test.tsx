import type { PropsWithChildren } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { makeUser } from "@/features/auth/test-fixtures";
import { currentUserQueryKey, useCurrentUser } from "@/features/auth/use-current-user";
import { server } from "@/test/msw";

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: PropsWithChildren) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useCurrentUser", () => {
  it("loads and caches the signed-in user", async () => {
    server.use(http.get("*/api/v1/users/me", () => HttpResponse.json(makeUser({ role: "admin" }))));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    const { result } = renderHook(() => useCurrentUser(), { wrapper: wrapper(client) });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.role).toBe("admin");
    expect(client.getQueryData(currentUserQueryKey)).toEqual(makeUser({ role: "admin" }));
  });
});
