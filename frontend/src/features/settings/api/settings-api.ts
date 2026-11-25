import { apiFetch } from "@/api/client";
import type { ChangePasswordInput } from "@/api/schema";

export async function changePassword(input: ChangePasswordInput): Promise<void> {
  await apiFetch<unknown>("/api/v1/auth/change-password", { method: "POST", body: input });
}
