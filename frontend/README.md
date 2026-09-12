# KernelWorx Frontend

React 19 + TypeScript single-page app for KernelWorx, built with Vite. It talks to the
KernelWorx AppSync GraphQL API (`/graphql`) using Apollo Client and authenticates users
with Amazon Cognito via AWS Amplify v6. The UI is MUI 7 (Emotion) on top of a custom
theme using the Atkinson Hyperlegible and Bricolage Grotesque brand fonts
(`docs/branding/`).

## Prerequisites

- Node.js >= 24 (see `../.node-version` at the repo root; `engines` in `package.json`)
- Dependencies installed with `npm ci` from this directory:

```bash
cd frontend
npm ci
```

## How the app is organized

`src/` is laid out by role:

| Path | Contents |
| --- | --- |
| `src/App.tsx` | Router and provider wiring. Every route is lazy-loaded via `lazyRoute()` (React.lazy + a per-route `ErrorBoundary`). Public routes render bare; everything else goes through `ProtectedAppRoute`, which nests `ProtectedRoute` (auth, optional `requireAdmin`) → `AppLayout` → `ErrorBoundary`. Campaign tabs live under the `/scouts/:profileId/campaigns/:campaignId/*` wildcard rendered by `CampaignLayout`. |
| `src/pages/` | One file per route page (27 pages, flat, plus `CampaignLayout.tsx`). |
| `src/components/` | Shared UI components (flat), plus `components/settings/` for the settings feature. |
| `src/contexts/AuthContext.tsx` | `AuthProvider`/`useAuth`: Amplify session handling, OAuth redirect restore, and the admin flag from the Cognito `cognito:groups` claim. |
| `src/hooks/` | Form and feature hooks (campaign form state machine, order form, MFA, passkeys, snackbar, ...), with an `index.ts` barrel for the user-settings hooks. |
| `src/lib/` | Infrastructure and utilities: the Apollo client (`apollo.ts`), Amplify/Cognito configuration (`amplify.ts`, `cognitoDomain.ts`), the GraphQL operations (`graphql.ts`), the MUI theme (`theme.ts`), and assorted helpers (dates, ids, report export, error handling, ...). |
| `src/constants/` | Shared enums/constants (campaign, unit types). |
| `src/types/` | `auth.ts` (hand-maintained types), `graphql-generated.ts` (generated — see below), re-exported from `index.ts`. |

State management is Apollo's normalized cache plus React context; there is no Redux or
similar store. The provider nesting in `App.tsx` is:
`ThemeProvider` → `ApolloProvider` → `BrowserRouter` → `AuthProvider`.

### GraphQL client

`src/lib/apollo.ts` builds the Apollo Client:

- **Endpoint**: `import.meta.env.VITE_APPSYNC_ENDPOINT ?? '/graphql'` — the deployed
  app is same-origin through CloudFront, so dev/prod builds leave the variable unset;
  local `vite dev` and ephemeral environments set an absolute AppSync URL (see below).
- **Link chain**: error link → auth link → HTTP link. The auth link pulls the Cognito
  ID token from Amplify (`fetchAuthSession`) and sets the `Authorization` header. The
  error link maps `extensions.errorCode` to user-facing messages and dispatches the
  `graphql-error` window event the toast UI listens to.
- **Cache**: `InMemoryCache` type policies replace-merge the paginated
  `listMyProfiles`, `listMyShares`, `listCampaignsByProfile`, and `listOrdersByCampaign`
  queries; default fetch policies are `cache-and-network` (watch queries) and
  `cache-first` (one-shot queries).

### Generated types (codegen)

GraphQL operations are written inline in `src/lib/graphql.ts` (and co-located in
components) as `gql` tags. TypeScript types for the schema and for every operation are
generated with GraphQL Code Generator:

```bash
npm run codegen
```

- **Schema source**: `../tofu/application/schema/schema.graphql` (the AppSync schema
  in this repo — no introspection against a live API needed).
- **Output**: `src/types/graphql-generated.ts`, which is **checked in**. Regenerate it
  whenever the schema or the operations change, and commit the result.
- **Convention**: generated types carry a `Gql` prefix (`GqlCampaign`,
  `GqlListMyProfilesQuery`, ...) so they never collide with the hand-maintained types in
  `auth.ts`. Import them from `types` (barrel) or `types/graphql-generated`.
- Config lives in `codegen.ts`; the output is auto-formatted with Prettier after
  generation.

## Configuration

All configuration is `VITE_*` environment variables (Vite exposes only these to the
browser). See `.env.example` for the full list:

| Variable | Purpose |
| --- | --- |
| `VITE_APPSYNC_ENDPOINT` | Direct AppSync URL (`...appsync-api.us-east-1.amazonaws.com/graphql`). Required for `vite dev`; unset for dev/prod builds (same-origin `/graphql`). |
| `VITE_APPSYNC_REGION` | AppSync region, e.g. `us-east-1`. |
| `VITE_COGNITO_USER_POOL_ID` / `VITE_COGNITO_USER_POOL_CLIENT_ID` | Cognito user pool and app client. |
| `VITE_COGNITO_DOMAIN` | Cognito custom domain (e.g. `login.dev.kernelworx.app`). Required for `vite dev`; unset for same-origin builds. |
| `VITE_OAUTH_REDIRECT_SIGNIN` / `VITE_OAUTH_REDIRECT_SIGNOUT` | OAuth callback URLs (e.g. `http://localhost:5173/`). |

## Running locally

```bash
npm run dev
```

Vite serves on port 5173 (`strictPort`). With no certificates present it serves plain
HTTP on all interfaces; if you need HTTPS (Cognito requires an HTTPS callback origin),
follow `LOCAL_DEV.md` — it covers the `local.dev.appworx.app` hosts entry, the
self-signed certs in `.cert/`, and `setup-local-dev.sh`, which generates both and
writes a ready-made `.env.local`.

To hit a real backend, fill in a copy of `.env.example` (as `.env` or `.env.local`)
with outputs from the deployed dev stack (`tofu output` — see `deploy.sh` for the exact
variable names, and `../docs/GETTING_STARTED.md` for the backend bring-up).

## Building

```bash
npm run build     # tsc -b && vite build → dist/
npm run preview   # serve the production build locally
```

`deploy.sh` wraps the build for the dev environment: it generates `.env.production`
with the same-origin variables, builds, syncs `dist/` to the S3 bucket, and creates a
CloudFront invalidation. CI builds the frontend the same way (`.github/workflows/deploy-shared.yml`).

## Testing

Unit and component tests use Vitest + jsdom + Testing Library, all under `tests/`
(with `tests/hooks/` and `tests/lib/` subdirectories and a global `tests/setup.ts`):

```bash
npm test                    # node run-tests.js → vitest run (CI uses: npm run test -- --coverage)
npm run test:coverage       # with v8 coverage report
npm run test:watch          # watch mode
npm run test:ui             # Vitest UI
```

`npm test` goes through `run-tests.js`, a wrapper that adds kill switches for the
known "Vitest + jsdom never exits" hang (5 minutes without output, 10 minutes total).
Coverage thresholds are enforced in `vite.config.ts` (lines 99 / functions 97 /
branches 96 / statements 97) — do not lower them without approval.

End-to-end smoke tests are Python pytest + Playwright and live outside this directory
in `../tests/e2e/` (run against `https://dev.kernelworx.app` or an ephemeral stack);
see `../tests/e2e/README.md` and `TESTING.md`.

## Lint, typecheck, format, spellcheck

```bash
npm run lint              # ESLint (also enforces complexity <= 5, max-depth <= 3)
npm run lint:complexity   # the two complexity rules as a one-off report
npm run typecheck         # tsc -b --noEmit && tsc -p tsconfig.test.json --noEmit
npm run format            # Prettier over src/**/*.{ts,tsx}
npm run spellcheck        # cspell against the root cspell.json
```

TypeScript is split across three configs: `tsconfig.app.json` (application code,
strict), `tsconfig.node.json` (Vite config), and `tsconfig.test.json` (adds the
`tests/` tree and Vitest globals).

CI runs the spellcheck from the repo root, then `npm run lint`, `npm run typecheck`,
and `npm run test -- --coverage` on every PR (`.github/workflows/ci.yml`, `frontend`
job).
