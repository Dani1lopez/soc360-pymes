import type { PropsWithChildren } from "react";
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";

export function AppProviders({
  children,
  queryClient,
}: PropsWithChildren<{ queryClient: QueryClient }>) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
