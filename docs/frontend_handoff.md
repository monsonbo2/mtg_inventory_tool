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
- `contracts/openapi.json`
- `contracts/demo_payloads/`

Those files define the response shapes, error envelope, and example payloads
the UI should expect.

Use `docs/frontend_backend_requests/` only as optional supporting context when
a GitHub issue links to a specific request doc. GitHub issues and pull requests
are the only live tracking surface for request status, ownership, and
discussion.

## Demo Scope

The current intended demo surface is:

- inventory selector
- card search
- card-name search plus printing lookup
- add card flow
- multi-row bulk edit
- CSV import preview/commit
- pasted decklist import preview/commit
- deck URL import preview/commit
- inventory transfer / duplicate flows
- CSV export download
- owned rows table
- quick edit for quantity, finish, location, notes, and tags
- recent audit activity

## Feature Map

Use this as the first-pass UI-to-endpoint map:

- Inventory selector -> `GET /inventories`
  Returns only the inventories visible to the current shared-service user.
  Inventory rows also include inventory metadata such as `default_location`,
  `default_tags`, `notes`, `acquisition_price`, and `acquisition_currency`.
- Card search -> `GET /cards/search`
- Card search scope guidance:
  - omit `scope` for the ordinary mainline add flow
  - use `scope=all` only for an intentional advanced or fallback broad-catalog
    search mode
- Card-name search -> `GET /cards/search/names`
  Returns one row per card/oracle and includes `available_languages`.
  The backend prefers token/prefix-style matches first and only falls back to
  broader substring rescue for selective longer single-token misses when those
  grouped matches are absent.
  - if the frontend opts into `scope=all`, keep that same scope choice when
    moving from card-name search to printing lookup
- Quick-add printing summary for a selected card ->
  `GET /cards/oracle/{oracle_id}/printings/summary`
  Returns the backend default add choice, available languages, scoped printing
  count, and the primary/preferred printings for the initial picker.
- Full printing lookup for a selected card -> `GET /cards/oracle/{oracle_id}/printings`
  Defaults to English printings when available; use `lang=all` or a specific
  language code to expand the list.
  - also accepts `scope=all` when the frontend intentionally wants the broader
    local catalog instead of the default mainline add-flow scope
- Add card -> `POST /inventories/{inventory_slug}/items`
  Accepts printing-level identifiers like `scryfall_id` and card-level
  `oracle_id`. When `language_code` is omitted, the backend stores the
  resolved printing language.
  - omitted `location` inherits the inventory `default_location` when present
  - omitted `tags` inherits the inventory `default_tags` when present
  - explicit non-empty `tags` merge with the inventory defaults
  - explicit blank `location` or blank `tags` intentionally bypass the
    inventory defaults
- Multi-row bulk edit -> `POST /inventories/{inventory_slug}/items/bulk`
  Request body is JSON.
  - use exactly one bulk `operation` per request
  - current operations are `add_tags`, `remove_tags`, `set_tags`,
    `clear_tags`, `set_quantity`, `set_notes`, `set_acquisition`,
    `set_finish`, `set_location`, and `set_condition`
  - `set_location` and `set_condition` can merge rows when `merge=true`, so
    the frontend should refetch the owned rows after successful merge-capable
    bulk mutations instead of assuming all original `item_id`s still exist
- CSV import preview/commit -> `POST /imports/csv`
  Request body is `multipart/form-data`.
  - use `dry_run=true` for preview
  - if `ready_to_commit` is `false`, show `resolution_issues` and resubmit the
    same file with `resolutions_json`
  - current backend CSV adapters are `generic_csv`,
    `tcgplayer_app_collection_csv`, `tcgplayer_legacy_collection_csv`,
    `manabox_collection_csv`, `mtggoldfish_collection_csv`,
    `deckbox_collection_csv`, `deckstats_collection_csv`, and
    `mtgstocks_collection_csv`
- Pasted decklist import preview/commit -> `POST /imports/decklist`
  Request body is JSON.
  - use `dry_run=true` for preview
  - if `ready_to_commit` is `false`, resubmit with `resolutions`
- Deck URL import preview/commit -> `POST /imports/deck-url`
  Request body is JSON.
  - use `dry_run=true` for preview
  - if `ready_to_commit` is `false`, resubmit with `resolutions`
  - preserve `source_snapshot_token` from preview and send it back on commit so
    the backend reuses the same signed remote deck snapshot instead of
    refetching the provider
  - current providers are `archidekt`, `aetherhub`, `manabox`, `moxfield`,
    `mtggoldfish`, `mtgtop8`, and `tappedout`
- Inventory transfer -> `POST /inventories/{source_inventory_slug}/transfer`
  Request body is JSON.
  - supports selected `item_ids` or `all_items=true`
  - use `mode=copy|move`
  - use `dry_run=true` to preview `copy`, `move`, `merge`, or `fail` outcomes
  - whole-inventory previews can truncate the returned per-row `results`, so
    use the summary counts as the authoritative top-level signal
- Duplicate inventory -> `POST /inventories/{source_inventory_slug}/duplicate`
  Request body is JSON.
  - creates a new inventory atomically and copies every source row into it
  - the response includes both the created inventory and the stable transfer
    summary payload
- CSV export download -> `GET /inventories/{inventory_slug}/export.csv`
  Uses `profile=default` today and returns `text/csv`.
- Owned rows table -> `GET /inventories/{inventory_slug}/items`
  Returned rows include `oracle_id`, `allowed_finishes`, and
  `printing_selection_mode` for printing-aware edit flows.
- Quick edit quantity -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"quantity": ...}`
- Quick edit finish -> `PATCH /inventories/{inventory_slug}/items/{item_id}`
  Request body: `{"finish": ...}`
- Change owned printing -> `PATCH /inventories/{inventory_slug}/items/{item_id}/printing`
  Request body: `{"scryfall_id": ...}` with optional `finish`, `merge`, and
  `keep_acquisition`.
  - use this for switching to a different printing of the same `oracle_id`
  - the current `scryfall_id` may be resubmitted only to confirm a defaulted
    selection as explicit when finish and language stay unchanged
  - same-printing finish edits still belong on the generic PATCH route
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
   cd frontend
   npm install
   npm run demo:bootstrap -- --force
   ```

   To validate shared-service onboarding and permission-aware empty states with
   stable actors and memberships:

   ```bash
   npm run demo:bootstrap -- --force --shared-service-fixtures
   ```

   Fixture users:

   - `new-user@example.com`: omit `X-Authenticated-Roles`; no readable
     inventory yet; can create a custom first collection
   - `bootstrapped@example.com`: omit `X-Authenticated-Roles`; owns
     `bootstrapped-collection`
   - `viewer@example.com`: omit `X-Authenticated-Roles`; `viewer` on
     `personal`
   - `writer@example.com`: omit `X-Authenticated-Roles`; `editor` on
     `trade-binder`
   - `no-access@example.com`: omit `X-Authenticated-Roles`; no memberships
   - `admin@example.com`: send `X-Authenticated-Roles: admin` for global bypass

   Or, if you want the frontend to search a real imported catalog instead of
   the tiny built-in demo catalog:

   ```bash
   npm run demo:bootstrap -- \
     --force \
     --full-catalog \
     --scryfall-json /path/to/default-cards.json
   ```

   If you also want imported MTGJSON pricing in that full-catalog demo:

   ```bash
   npm run demo:bootstrap -- \
     --force \
     --full-catalog \
     --scryfall-json /path/to/default-cards.json \
     --identifiers-json /path/to/AllIdentifiers.json \
     --prices-json /path/to/AllPricesToday.json
   ```

   In full-catalog mode the bootstrap still creates the same curated demo
   inventories and owned-row states, but it resolves those rows against real
   imported printings using the same default `oracle_id` printing policy as the
   app. If the imported catalog cannot satisfy one of the intended demo states,
   the bootstrap now fails early with a clear seed-resolution error. Without the
   optional MTGJSON files, full-catalog mode keeps the curated demo price seed
   for the showcase owned rows only.

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

2. Install the backend web dependencies if you have not already:

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

3. Start the backend locally:

   ```bash
   npm run backend:demo
   ```

   If you are working against an upgraded existing pre-`0008` database instead
   of a fresh bootstrap, run a fresh Scryfall import before relying on the
   narrowed default catalog search scope.

4. Point the frontend at the local API base URL.
5. Build against the published HTTP contract rather than backend internals.

## Frontend Quick Start

- Backend command:
  `npm run backend:demo`
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

Proxy-backed shared-service preflight:

```bash
cd frontend
npm run demo:bootstrap -- --force --shared-service-fixtures
npm run build
npm run smoke:shared-service-proxy -- --start-backend
```

For a manual browser pass against one fixture identity, start the backend in
`shared_service` and run `npm run proxy:shared-service -- --fixture-preset
viewer`. The local harness is a validation tool only; use a real reverse proxy
or gateway for users.

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
- Open or update a GitHub issue with
  `.github/ISSUE_TEMPLATE/frontend-backend-request.yml` for frontend requests
  into the backend/API layer. Use
  `docs/frontend_backend_requests/README.md` only when extra supporting
  contract detail is worth keeping in-repo. Keep live tracking in GitHub
  issues/PRs only; local request docs are optional supporting specs, not
  status boards.
- The frontend may do UX validation, but backend validation remains the source
  of truth.
- In `local_demo`, `X-Actor-Id` is ignored by default by the API shell. Audit
  writes will appear as `local-demo` unless trusted-header mode is
  deliberately enabled.
- `shared_service` uses verified upstream identity headers such as
  `X-Authenticated-User` and optionally `X-Authenticated-Roles`; frontend code
  should not treat `X-Actor-Id` as the shared-service auth model. A missing
  roles header means the user has no global roles, not that they are a global
  `editor`.
- Shared-service inventory access is now membership-scoped. Frontend code
  should assume:
  - inventory lists are filtered to the current user
  - some inventory reads may return `403`
  - inventory writes may return `403` if the user is a viewer or non-member
  - catalog search should not be treated as globally available to every
    authenticated user; it currently requires a user who can read at least one
    inventory, or a global `admin`
  - authenticated users can create inventories they own
  - first-run frontend users should use the normal create-inventory flow when
    they need a custom first collection name

## Known Limits

- The current frontend sandbox should keep using the default `local_demo` API
  posture for local work.
- The backend now also has a `shared_service` startup mode for pre-migrated,
  single-host deployments. In that mode, the app uses verified upstream
  identity plus local inventory memberships rather than one global permission
  domain. Broader deployment policy and admin-only surface policy are not
  finished yet.
- Deck URL preview/commit flows now depend on the backend-issued
  `source_snapshot_token`; frontend code should treat that token as opaque and
  short-lived rather than trying to inspect or modify it.
- The recommended first-live deployment shape is same-origin and proxy-based,
  not separate-origin CORS.
- The backend still uses synchronous SQLite-backed services under the HTTP
  layer, with sync HTTP route handlers aligned to that service boundary.
- The current backend permission model is now inventory-scoped for reads and
  writes, but still intentionally small:
  - proxy-backed global app roles: `editor`, `admin`
  - local inventory roles: `viewer`, `editor`, `owner`
  - no richer org/team/ownership workflow exists yet
- For shared-service first-run state, prefer `GET /me/access-summary` as the
  frontend startup probe:
  - if `has_readable_inventory` is `true`, continue normally
  - else if `can_bootstrap` is `true`, offer the custom create-inventory flow
  - else show an authenticated access-needed or unavailable state
- Browser-based local dev is expected to use a frontend proxy unless backend
  CORS behavior is changed deliberately.
