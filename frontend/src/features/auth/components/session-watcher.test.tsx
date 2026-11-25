import { act } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { SESSION_CLEARED_EVENT } from "@/api/session";
import { createTestQueryClient, renderWithQueryClient } from "@/test/render";
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
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(["sample"], "cached");
  const view = renderWithQueryClient(<SessionWatcher />, queryClient);
  return view;
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
