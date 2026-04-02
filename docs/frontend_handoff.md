# Frontend Handoff

This document defines the intended boundary between the existing Python backend
and a separate frontend sandbox.

## Goal

Let a frontend specialist build the demo UI against a stable HTTP contract
without editing backend implementation code directly.

## Ownership Boundary

Backend-owned paths:

- `src/mtg_source_stack/`
- `tests/`
- `docs/api_v1_contract.md`
- `docs/backend_v1_contract.md`
- `docs/frontend_handoff.md`
- `contracts/openapi.json`
- `contracts/demo_payloads/`

Frontend-owned path:

- `frontend/`

The shared integration surface is HTTP only. The frontend should not import or
replicate Python-side business logic.

## Handoff Artifacts

The frontend sandbox should treat these as the source of truth:

- `docs/api_v1_contract.md`
- `docs/frontend_backend_requests/`
- `contracts/openapi.json`
- `contracts/demo_payloads/`

Those files define the response shapes, error envelope, and example payloads
the UI should expect.

## Demo Scope

The current intended demo surface is:

- inventory selector
- card search
- card-name search plus printing lookup
- add card flow
- owned rows table
- quick edit for quantity, finish, location, notes, and tags
- recent audit activity

## Feature Map

Use this as the first-pass UI-to-endpoint map:

- Inventory selector -> `GET /inventories`
- Card search -> `GET /cards/search`
- Card-name search -> `GET /cards/search/names`
  Returns one row per card/oracle and includes `available_languages`.
- Printing lookup for a selected card -> `GET /cards/oracle/{oracle_id}/printings`
  Defaults to English printings when available; use `lang=all` or a specific
  language code to expand the list.
- Add card -> `POST /inventories/{inventory_slug}/items`
  Accepts printing-level identifiers like `scryfall_id` and card-level
  `oracle_id`. When `language_code` is omitted, the backend stores the
  resolved printing language.
- Owned rows table -> `GET /inventories/{inventory_slug}/items`
  Returned rows include `allowed_finishes` for safe finish-edit controls.
- Quick edit quantity -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"quantity": ...}`
- Quick edit finish -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"finish": ...}`
- Quick edit location -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"location": ...}`
- Quick edit notes -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"notes": ...}`
- Quick edit tags -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"tags": [...]}` or `{"clear_tags": true}`
- Remove card -> `DELETE /inventories/{inventory_slug}/items/{item_id}`
- Recent activity -> `GET /inventories/{inventory_slug}/audit`

## Local Dev Flow

1. Bootstrap a local demo database:

   ```bash
   python3 scripts/bootstrap_frontend_demo.py --db var/db/frontend_demo.db --force
   ```

2. Start the backend locally:

   ```bash
   pip install -e '.[web]'
   mtg-web-api --db var/db/frontend_demo.db
   ```

3. Point the frontend at the local API base URL.
4. Build against the published HTTP contract rather than backend internals.

## Frontend Quick Start

- Backend command:
  `mtg-web-api --db var/db/frontend_demo.db`
- Expected API base URL:
  `http://127.0.0.1:8000`
- Preferred browser-dev setup:
  use a frontend dev proxy and talk to the backend through `/api` or your
  framework's equivalent proxy base path
- Why proxy first:
  the demo API does not enable CORS by default, so a browser dev server on a
  different origin will otherwise hit cross-origin restrictions
- If you do not want a proxy:
  coordinate a backend change first instead of silently working around the
  current API boundary
- For the first live shared-service deployment:
  assume a same-origin reverse proxy that publishes `/api` publicly and strips
  that prefix before forwarding to the backend root-route API

Example Vite proxy:

```ts
export default {
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
}
```

## Working Rules

- Frontend changes stay inside `frontend/` unless you explicitly request a
  backend contract change.
- Backend changes should be requested as API-contract work, not merged in as
  opportunistic UI edits.
- Use `docs/frontend_backend_requests/README.md` plus the GitHub issue template
  at `.github/ISSUE_TEMPLATE/frontend-backend-request.yml` for frontend
  requests into the backend/API layer.
- The frontend may do UX validation, but backend validation remains the source
  of truth.
- In `local_demo`, `X-Actor-Id` is ignored by default by the API shell. Audit
  writes will appear as `local-demo` unless trusted-header mode is
  deliberately enabled.
- `shared_service` uses verified upstream identity headers such as
  `X-Authenticated-User` and optionally `X-Authenticated-Roles`; frontend code
  should not treat `X-Actor-Id` as the shared-service auth model.

## Known Limits

- The current frontend sandbox should keep using the default `local_demo` API
  posture for local work.
- The backend now also has a `shared_service` startup mode for pre-migrated,
  single-host deployments. In that mode, all current non-health routes require
  an authenticated `editor` user, and `admin` is reserved for maintenance
  surfaces. Broader deployment policy is not finished yet.
- The recommended first-live deployment shape is same-origin and proxy-based,
  not separate-origin CORS.
- The backend still uses synchronous SQLite-backed services under the HTTP
  layer, with sync HTTP route handlers aligned to that service boundary.
- The current backend permission model is intentionally coarse:
  authenticated `editor` access for the app routes, with `admin` reserved for
  maintenance surfaces.
- Browser-based local dev is expected to use a frontend proxy unless backend
  CORS behavior is changed deliberately.
