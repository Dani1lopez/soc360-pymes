import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { SESSION_CLEARED_EVENT } from "@/api/session";

export function SessionWatcher() {
  const queryClient = useQueryClient();
  const router = useRouter();
  useEffect(() => {
    const onSessionCleared = () => {
      queryClient.clear();
      const location = router.state.location;
      if (location.pathname !== "/login") {
        void router.navigate({ to: "/login", search: { redirect: location.href } });
      }
    };
    window.addEventListener(SESSION_CLEARED_EVENT, onSessionCleared);
    return () => window.removeEventListener(SESSION_CLEARED_EVENT, onSessionCleared);
  }, [queryClient, router]);
  return null;
}
