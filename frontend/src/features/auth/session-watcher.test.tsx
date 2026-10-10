import { act, render } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { SESSION_CLEARED_EVENT } from "@/api/session";
import { createQueryClient } from "@/app/query-client";
import { SessionWatcher } from "./session-watcher";

const router = vi.hoisted(() => ({
  state: { location: { pathname: "/login", href: "/login" } },
  navigate: vi.fn(),
}));
vi.mock("@tanstack/react-router", () => ({ useRouter: () => router }));
beforeEach(() => {
  router.navigate.mockReset();
  router.state.location = { pathname: "/login", href: "/login" };
});
function mount() {
  const queryClient = createQueryClient();
  queryClient.setQueryData(["sample"], "cached");
  const view = render(
    <QueryClientProvider client={queryClient}>
      <SessionWatcher />
    </QueryClientProvider>,
  );
  return { queryClient, ...view };
}
test("clears queries without navigating when already on login", () => {
  const { queryClient } = mount();
  act(() => window.dispatchEvent(new Event(SESSION_CLEARED_EVENT)));
  expect(queryClient.getQueryData(["sample"])).toBeUndefined();
  expect(router.navigate).not.toHaveBeenCalled();
});
test("preserves the current destination when navigating", () => {
  router.state.location = { pathname: "/forbidden", href: "/forbidden?x=1" };
  mount();
  act(() => window.dispatchEvent(new Event(SESSION_CLEARED_EVENT)));
  expect(router.navigate).toHaveBeenCalledWith({
    to: "/login",
    search: { redirect: "/forbidden?x=1" },
  });
});
test("removes the listener on unmount", () => {
  const { queryClient, unmount } = mount();
  unmount();
  act(() => window.dispatchEvent(new Event(SESSION_CLEARED_EVENT)));
  expect(queryClient.getQueryData(["sample"])).toBe("cached");
  expect(router.navigate).not.toHaveBeenCalled();
});
