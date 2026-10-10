import type { components, paths } from "@/api/types";

// Narrow, stable aliases over the generated OpenAPI types (`src/api/types.ts`,
// regenerated with `pnpm gen:api`). Feature code imports from here, never from
// the generated file, so a regeneration only has to be reconciled in one place.
export type ApiPaths = paths;
export type ApiSchemas = components["schemas"];

export type TokenResponse = ApiSchemas["TokenResponse"];
export type UserResponse = ApiSchemas["UserResponse"];
export type Role = ApiSchemas["RoleEnum"];
export type LoginRequest = ApiSchemas["LoginRequest"];
