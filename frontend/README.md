# SOC360 PyMEs — Frontend

Single-page application for the SOC360 PyMEs multi-tenant dashboard. It talks to
the FastAPI backend under `/api/v1` and is served same-origin in production so
the backend's `SameSite=Strict` refresh cookie keeps working.

## Stack

| Concern         | Choice                                   |
| --------------- | ---------------------------------------- |
| Build tool      | Vite 8                                   |
| UI              | React 18 + TypeScript (strict)           |
| Styling         | Tailwind CSS 4 + shadcn/ui               |
| Routing         | TanStack Router                          |
| Server state    | TanStack Query                           |
| API types       | `openapi-typescript` from `openapi.json` |
| Tests           | Vitest + Testing Library (jsdom)         |
| Package manager | pnpm 11 (Node >= 20)                     |

## Getting started

```bash
pnpm install
pnpm dev            # http://localhost:5173
```

The dev server proxies `/api` to the backend. Point it somewhere else with a
server-only variable in `frontend/.env.local`:

```bash
VITE_API_PROXY_TARGET=http://localhost:8000
```

`vite.config.ts` sets `envPrefix: "VITE_PUBLIC_"`, so `VITE_API_PROXY_TARGET`
stays on the dev server and is never exposed to the browser bundle. Only
variables prefixed `VITE_PUBLIC_` reach the client.

Start the backend (with PostgreSQL and Redis) from the repository root with
`docker compose up` or `uv run uvicorn app.main:app --reload`.

## Scripts

| Command                             | Purpose                                           |
| ----------------------------------- | ------------------------------------------------- |
| `pnpm dev`                          | Vite dev server with the API proxy                |
| `pnpm build`                        | Typecheck (`tsc -b`) then production build        |
| `pnpm typecheck`                    | TypeScript project build, no emit                 |
| `pnpm lint`                         | ESLint over the workspace                         |
| `pnpm format` / `pnpm format:check` | Prettier write / verify                           |
| `pnpm test` / `pnpm test:watch`     | Vitest once / in watch mode                       |
| `pnpm e2e`                          | Playwright smoke against the real API and Vite    |
| `pnpm gen:api`                      | Regenerate `src/api/types.ts` from `openapi.json` |

The router plugin regenerates committed `src/routeTree.gen.ts` during dev/build.
Do not edit it by hand; CI checks for route-tree drift after the build.

`pnpm e2e` runs the Playwright smoke under `e2e/`. It expects the backend and the
Vite dev server to be running already (it does not start them). The full journey
signs in with the development credentials, passed in a single environment variable
that is never stored in the repository:

```bash
cd frontend
E2E_LOGIN='correo:valor' pnpm e2e   # panel, activos, escaneos, vulnerabilidades, informes
pnpm e2e                            # without it, only the boot-and-theme check runs
```

The gate before pushing is:

```bash
pnpm lint && pnpm typecheck && pnpm test && pnpm format:check && pnpm build
```

## API types and the snapshot

`openapi.json` is a deterministic snapshot of the backend schema, produced
without a running server:

```bash
# From the repository root
uv run python scripts/dump_openapi.py          # refresh the snapshot
uv run python scripts/dump_openapi.py --check  # CI: fail when it is stale

# From frontend/
pnpm gen:api                                   # regenerate src/api/types.ts
```

CI runs both checks: the Python job verifies the snapshot, and the frontend job
regenerates the types and fails on a diff. Commit `openapi.json` and
`src/api/types.ts` together with the backend change that caused them.

`src/api/schema.ts` re-exports narrow aliases over the generated file. Feature
code imports from there, so a regeneration only has to be reconciled in one
place.

## Source layout

```
src/
  main.tsx           entry point
  app/               providers, query client, router composition
  routes/            file-based routes: thin adapters
  routeTree.gen.ts   generated route tree (committed)
  features/<f>/      api/, hooks/, components/, lib/, index.ts (public API)
  api/               HTTP client, session, errors, schema aliases, generated types
  components/ui/     shared shadcn components
  lib/               shared utilities
  test/              setup, MSW server, fixtures, render helpers
```

- App and routes depend on features only through `@/features/<f>` public indexes.
  Routes are thin adapters; guards and pages live in features.
- Features depend on shared `api/`, `components/`, and `lib/`, never app, routes,
  or another feature's internals. Use relative imports inside a feature.
- Shared code never depends on features, app, or routes. Test helpers may use
  shared code and feature public indexes, never app or routes. App integration
  tests live in `src/app/*.test.tsx` and may import any layer.
- Import API types from `@/api/schema`; only that module imports generated types.
  ESLint enforces alias-based layer boundaries.

To add a feature, create `src/features/<f>/` with its implementation and expose
its public API through `index.ts`. Then add a file under `src/routes/` that wires
feature guards and pages. Run dev/build to regenerate and commit the route tree.

## Sessions

- The access token lives in memory only and is attached by `apiFetch`.
- The refresh cookie is `HttpOnly`; the SPA never reads it.
- A `401` triggers one single-flight refresh and one retry. The refresh is
  serialized across tabs with the Web Locks API and the new token is shared
  through a `BroadcastChannel`, so two tabs never race on the same rotating
  cookie.
- After a page reload the bearer is gone from memory, so the authenticated
  layout calls `restoreSession()`, which refreshes through the cookie before
  deciding whether there is a session.
- `SESSION_CLEARED_EVENT` fires on the `window` when the session is gone, in this
  tab or a sibling one. `SessionWatcher` then clears the query cache and sends
  the user to `/login?redirect=<current path>`.
- After login, the `redirect` destination is kept only when it resolves to the
  same origin (`sanitizeRedirect`); anything else falls back to `/`.

## Routes and roles

Role checks mirror the backend `require_any_role` allowlists: exact role match,
no hierarchy, and no `is_superadmin` shortcut.

| Route group              | Guard                                            | Pages                                                                                                  |
| ------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `/login`                 | redirects signed-in users away                   | Login                                                                                                  |
| `_authenticated`         | session + `/users/me` (`requireSession`)         | shell, `/forbidden`                                                                                    |
| `_authenticated/_reader` | `READ_ROLES`: viewer, analyst, admin, superadmin | `/` (panel), `/assets`, `/scans`, `/scans/$id`, `/vulnerabilities`, `/vulnerabilities/$id`, `/reports` |
| `_authenticated/_admin`  | `ADMIN_ROLES`: admin, superadmin                 | `/users`, `/settings`                                                                                  |

A role outside a group's allowlist lands on `/forbidden`. The `ingestor` role is
for machines and reaches no page. Every page is real: the panel aggregates
`/dashboard/summary`, the reader pages manage assets, scans, findings (with their
enrichment panel) and report metadata, and the admin group manages users, the
tenant configuration and the password change. Each group has its own
`errorComponent`, so a page failure no longer looks like a session failure, and
the sidebar comes from `features/shell/lib/navigation.ts`, which filters entries
with the same allowlists.

Write actions follow the backend allowlists: they are hidden — not just refused —
when the signed-in role cannot perform them, and a superadmin without a tenant is
asked to pick an organisation instead of being offered a form that cannot work.

## Conventions

See `AGENTS.md` at the repository root for the review rules that apply to this
package.
