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
  Returns only the inventories visible to the current shared-service user.
- Card search -> `GET /cards/search`
- Card search scope guidance:
  - omit `scope` for the ordinary mainline add flow
  - use `scope=all` only for an intentional advanced or fallback broad-catalog
    search mode
- Card-name search -> `GET /cards/search/names`
  Returns one row per card/oracle and includes `available_languages`.
  - if the frontend opts into `scope=all`, keep that same scope choice when
    moving from card-name search to printing lookup
- Printing lookup for a selected card -> `GET /cards/oracle/{oracle_id}/printings`
  Defaults to English printings when available; use `lang=all` or a specific
  language code to expand the list.
  - also accepts `scope=all` when the frontend intentionally wants the broader
    local catalog instead of the default mainline add-flow scope
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

   Or, if you want the frontend to search a real imported catalog instead of
   the tiny built-in demo catalog:

   ```bash
   python3 scripts/bootstrap_frontend_demo.py \
     --db var/db/frontend_demo.db \
     --force \
     --full-catalog \
     --scryfall-json /path/to/default-cards.json
   ```

   In full-catalog mode the bootstrap still creates the same curated demo
   inventories and owned-row states, but it resolves those rows against real
   imported printings using the same default `oracle_id` printing policy as the
   app. If the imported catalog cannot satisfy one of the intended demo states,
   the bootstrap now fails early with a clear seed-resolution error.

   Refresh guidance:

   - the recommended local demo workflow already recreates the demo database
     with `--force`, so no separate refresh step is needed when you follow this
     bootstrap flow
   - the small built-in demo catalog only seeds mainline add-flow cards, so it
     is already compatible with the narrowed default search scope
   - full-catalog mode already performs a fresh Scryfall import during
     bootstrap, so it also starts with the correct catalog classification
   - only reused older pre-`0008` databases need an extra Scryfall refresh
     before relying on the narrowed default search scope

2. Start the backend locally:

   ```bash
   pip install -e '.[web]'
   mtg-web-api --db var/db/frontend_demo.db
   ```

   If you are working against an upgraded existing pre-`0008` database instead
   of a fresh bootstrap, run a fresh Scryfall import before relying on the
   narrowed default catalog search scope.

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
- Shared-service inventory access is now membership-scoped. Frontend code
  should assume:
  - inventory lists are filtered to the current user
  - some inventory reads may return `403`
  - inventory writes may return `403` if the user is a viewer or non-member
  - catalog search should not be treated as globally available to every
    authenticated user; it currently requires a user who can read at least one
    inventory, or a global `admin`
  - first-run shared-service users can call `POST /me/bootstrap` to create a
    personal `Collection` inventory and unlock search/add flows

## Known Limits

- The current frontend sandbox should keep using the default `local_demo` API
  posture for local work.
- The backend now also has a `shared_service` startup mode for pre-migrated,
  single-host deployments. In that mode, the app uses verified upstream
  identity plus local inventory memberships rather than one global permission
  domain. Broader deployment policy and admin-only surface policy are not
  finished yet.
- The recommended first-live deployment shape is same-origin and proxy-based,
  not separate-origin CORS.
- The backend still uses synchronous SQLite-backed services under the HTTP
  layer, with sync HTTP route handlers aligned to that service boundary.
- The current backend permission model is now inventory-scoped for reads and
  writes, but still intentionally small:
  - proxy-backed global app roles: `editor`, `admin`
  - local inventory roles: `viewer`, `editor`, `owner`
  - no richer org/team/ownership workflow exists yet
- Browser-based local dev is expected to use a frontend proxy unless backend
  CORS behavior is changed deliberately.
