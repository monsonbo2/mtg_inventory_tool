# Frontend Sandbox

This directory now contains the local-demo frontend scaffold.

## Boundary

The frontend should treat the backend as an HTTP service and should not edit or
depend on Python implementation details under `src/mtg_source_stack/`.

Use these as the integration contract:

- `../docs/api_v1_contract.md`
- `../docs/frontend_handoff.md`
- `../docs/frontend_backend_requests/`
- `../contracts/openapi.json`
- `../contracts/demo_payloads/`

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

1. Bootstrap a demo database:

   ```bash
   python3 ../scripts/bootstrap_frontend_demo.py --db ../var/db/frontend_demo.db --force
   ```

2. Install the backend web dependencies if you have not already:

   ```bash
   pip install -e '..[web]'
   ```

3. Start the API from this checkout:

   ```bash
   npm run backend:demo
   ```

   This launcher forces `PYTHONPATH` to the current repo's `src/` tree before
   starting the backend. Use it instead of a globally installed `mtg-web-api`
   wrapper when you have more than one local checkout of `mtg_source_stack`, or
   the demo can fail with a false `schema_not_ready` mismatch against another
   repo's migration set.

4. Install the frontend dependencies:

   ```bash
   npm install
   ```

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

## Working Agreement

- Keep all UI code under `frontend/`.
- Request backend contract changes instead of editing backend files directly.
  Use `../docs/frontend_backend_requests/README.md` and the GitHub issue
  template at `../.github/ISSUE_TEMPLATE/frontend-backend-request.yml`.
- Do not duplicate backend business rules unless they are purely presentational.
