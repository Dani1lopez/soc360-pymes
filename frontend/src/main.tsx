import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "@tanstack/react-router";
import { AppProviders } from "@/app/providers";
import { createAppRouter } from "@/app/router";
import { createQueryClient } from "@/app/query-client";
import "@/index.css";

const queryClient = createQueryClient();
const router = createAppRouter({ queryClient });

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing application root element");
}

createRoot(root).render(
  <StrictMode>
    <AppProviders queryClient={queryClient}>
      <RouterProvider router={router} />
    </AppProviders>
  </StrictMode>,
);
