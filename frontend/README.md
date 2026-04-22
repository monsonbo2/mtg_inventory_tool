# Frontend Sandbox

This directory now contains the local-demo frontend scaffold.

## Boundary

The frontend should treat the backend as an HTTP service and should not edit or
depend on Python implementation details under `src/mtg_source_stack/`.

Use these as the integration contract:

- `../docs/api_v1_contract.md`
- `../docs/frontend_handoff.md`
- `../contracts/openapi.json`
- `../contracts/demo_payloads/`

Use `../docs/frontend_backend_requests/` only when a GitHub issue points to a
supporting spec or historical note.

## Stack

The scaffold uses:

- Vite
- React
- TypeScript

## Current Scope

The first demo UI is expected to cover:

- inventory selection
- card search and add flow
- owned item list
- quick edit flows
- recent audit activity

## Environment

Copy `.env.example` to `.env.local` for local work.

The current scaffold expects:

- browser-facing API base URL: `/api`
- proxy target: `http://127.0.0.1:8000`

The proxy rewrites `/api/*` to `/*` because the current backend serves
root-mounted routes such as `/inventories` and `/cards/search`.

## Quick Start

1. Install the frontend dependencies:

   ```bash
   npm install
   ```

2. Bootstrap a demo database:

   ```bash
   npm run demo:bootstrap -- --force
   ```

   To seed the shared-service validation actors and memberships used for
   permission-aware frontend states:

   ```bash
   npm run demo:bootstrap -- --force --shared-service-fixtures
   ```

   Pass extra bootstrap args through npm when needed:

   ```bash
   npm run demo:bootstrap -- --full-catalog --scryfall-json /path/to/default-cards.json --force
   ```

   If you also want real MTGJSON-backed price snapshots in that full-catalog
   demo database, provide both local MTGJSON files too:

   ```bash
   npm run demo:bootstrap -- \
     --full-catalog \
     --scryfall-json /path/to/default-cards.json \
     --identifiers-json /path/to/AllIdentifiers.json \
     --prices-json /path/to/AllPricesToday.json \
     --force
   ```

   Without those MTGJSON inputs, full-catalog mode still uses the curated demo
   price seed for the owned showcase rows only.

3. Install the backend web dependencies if you have not already:

   ```bash
   cd ..
   python3 -m venv .venv
   . .venv/bin/activate
   pip install -e '.[web]'
   cd frontend
   ```

   The frontend demo launchers prefer `../.venv/bin/python` automatically when
   it exists. If you use a different environment, set
   `MTG_FRONTEND_PYTHON=/path/to/python`.

4. Start the API from this checkout:

   ```bash
   npm run backend:demo
   ```

   This launcher forces `PYTHONPATH` to the current repo's `src/` tree and
   prefers the repo-local virtualenv before falling back to `python3`. Use it
   instead of a globally installed `mtg-web-api` wrapper when you have more
   than one local checkout of `mtg_source_stack`, or the demo can fail with a
   false `schema_not_ready` mismatch against another repo's migration set.

5. Start the frontend:

   ```bash
   npm run dev
   ```

6. Open the local Vite URL, usually `http://127.0.0.1:5173`.

If you need to point the launcher at a different database, pass explicit API
args through npm:

```bash
npm run backend:demo -- --db /absolute/path/to/other.db
```

## Current UI Shape

The scaffold currently includes:

- an inventory selector
- a card search panel
- an add-card form driven by search results
- an owned-row editor with single-field save actions
- a recent audit feed

Quick edits intentionally follow the backend's current one-field-per-`PATCH`
contract, and PATCH responses include an explicit `operation` discriminator the
client can branch on. If the backend later expands that contract, the client
can be updated from one place in `src/api.ts` and the row editor flow.

## Proxy Notes

Prefer the Vite dev proxy instead of direct browser cross-origin calls.

The current demo API does not enable CORS by default. If your dev server runs
on another origin such as `localhost:5173`, proxy API requests back to
`http://127.0.0.1:8000`.

Current Vite proxy:

```ts
"/api": {
  target: "http://127.0.0.1:8000",
  rewrite: (path) => path.replace(/^\/api/, ""),
}
```

## Shared-Service Fixtures

Use `npm run demo:bootstrap -- --force --shared-service-fixtures` when you need
stable shared-service actors for onboarding and permission-state validation.
Start the backend in `shared_service` against that DB and inject the headers
below through your proxy or API client.

| User | Roles header | Expected state |
| --- | --- | --- |
| `new-user@example.com` | omit | No readable inventories yet; can create a custom first collection. |
| `bootstrapped@example.com` | omit | Owns `bootstrapped-collection`; readable inventory count is `1`. |
| `viewer@example.com` | omit | Viewer on `personal`; reads are allowed, writes are denied. |
| `writer@example.com` | omit | Editor on `trade-binder`; reads and writes are allowed there. |
| `no-access@example.com` | omit | No memberships or readable inventories yet; can create a custom first collection. |
| `admin@example.com` | `admin` | Global admin bypass; all demo inventories are visible. |

Check `GET /me/access-summary` first for each user. Then verify
`GET /inventories`, catalog search availability, inventory reads, and denied
writes match the table above. Owner/admin membership-management checks can use
`GET /inventories/{inventory_slug}/members` plus the matching POST/PATCH/DELETE
member routes.

`GET /inventories` now includes capability fields for permission-aware UI:
`role`, `can_read`, `can_write`, `can_manage_share`, and `can_transfer_to`.
Use those fields to gate write, import, transfer, duplicate, and share-link
controls instead of rendering the control first and relying on a later `403`.

## Proxy-Backed Shared-Service Validation

Use the local proxy harness when you need to validate the same-origin `/api`
rollout shape instead of the Vite dev proxy shortcut. The harness strips
client-supplied auth headers, injects one fixture identity, serves the built
frontend, and proxies `/api/*` to the root-mounted backend.

One-command smoke check:

```bash
npm run demo:bootstrap -- --force --shared-service-fixtures
npm run build
npm run smoke:shared-service-proxy -- --start-backend
```

The smoke workflow starts `mtg-web-api` in `shared_service`, starts local proxy
instances for fixture users, and verifies `/api` rewriting, spoofed-header
stripping, fixture visibility, search denial, and same-origin frontend serving.

For manual browser validation, start the shared-service backend and then run
the proxy with the fixture user you want to exercise:

```bash
MTG_API_SNAPSHOT_SIGNING_SECRET="local-shared-service-dev-secret" \
npm run backend:demo -- --runtime-mode shared_service --no-auto-migrate

npm run build
npm run proxy:shared-service -- --fixture-preset viewer
```

Open `http://127.0.0.1:5174`. Supported fixture presets are `new-user`,
`bootstrapped`, `viewer`, `writer`, `no-access`, `admin`, and `none`.

This harness is a local preflight tool only. Use a production reverse proxy or
gateway for real users; the transition is tracked in issue #57.

## Working Agreement

- Keep all UI code under `frontend/`.
- Request backend contract changes instead of editing backend files directly.
  Use `../docs/frontend_backend_requests/README.md` and the GitHub issue
  template at `../.github/ISSUE_TEMPLATE/frontend-backend-request.yml`.
  GitHub issues and PRs are the only live tracking surface; local request docs
  are optional supporting specs and historical context.
- Do not duplicate backend business rules unless they are purely presentational.
