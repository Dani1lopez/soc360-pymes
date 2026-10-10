# Code Review Rules

## Python
- Use type hints where practical.
- Prefer small, focused changes.
- Keep tests aligned with behavior changes.

## FastAPI
- Preserve existing API contracts unless the change explicitly requires a break.
- Keep validation and service logic easy to test.

## TypeScript / React (`frontend/`)
- Strict TypeScript: no `any`; narrow `unknown` with explicit guards.
- Folder architecture: `app/` composes providers and routing; `routes/` contains thin
  adapters; guards and pages live in `features/<f>/`. Shared code lives in `api/`,
  `components/`, and `lib/`; test helpers live in `test/`.
- Each feature exposes only `index.ts`. App and routes import `@/features/<f>`;
  features use relative internal imports and may depend on shared code, never
  app, routes, or another feature's internals.
- Shared code never imports features, app, or routes. Test helpers may import
  shared code and feature public indexes, never app or routes; app integration
  tests live in `src/app/*.test.tsx` and may import any layer.
- Do not edit `src/routeTree.gen.ts` by hand; the router plugin generates it.
- Feature code imports API types from `src/api/schema.ts`, never from the generated
  `src/api/types.ts` (regenerated with `pnpm gen:api`).
- Every API call goes through `apiFetch` in `src/api/client.ts`; components never call
  `fetch` directly.
- The access token stays in memory (`src/api/session.ts`); never persist it in
  `localStorage` or `sessionStorage`.
- Colocate tests as `*.test.ts(x)` and drive them with Vitest + Testing Library.
- Keep presentational components free of data fetching; isolate queries in hooks.
- The frontend gate is `pnpm lint && pnpm typecheck && pnpm test && pnpm format:check && pnpm build`;
  never run `ruff` on it.
