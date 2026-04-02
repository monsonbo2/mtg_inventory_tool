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
- add card flow
- owned rows table
- quick edit for quantity, finish, location, notes, and tags
- recent audit activity

## Feature Map

Use this as the first-pass UI-to-endpoint map:

- Inventory selector -> `GET /inventories`
- Card search -> `GET /cards/search`
- Add card -> `POST /inventories/{inventory_slug}/items`
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
- `X-Actor-Id` is ignored by default by the API shell. Audit writes will appear
  as `local-demo` unless trusted-header mode is deliberately enabled.

## Known Limits

- The current API shell is suitable for local/demo use, not shared deployment.
- The backend still uses synchronous SQLite-backed services under the HTTP
  layer.
- Authentication and permissions are not implemented yet.
- Browser-based local dev is expected to use a frontend proxy unless backend
  CORS behavior is changed deliberately.
