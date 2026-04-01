# Frontend Backend Request: API Base Path Compatibility

Status: Proposed
Owner: Unassigned
GitHub issue: Not linked yet
Implementation PR: Not linked yet
Last updated: 2026-04-01

## Frontend Backend Request

Feature / screen:

Local frontend dev proxy and shared API client setup

Current blocker:

The published frontend guidance tells browser-based clients to use `/api` as
the local base path and proxy that prefix to `http://127.0.0.1:8000`.
The live demo API routes are currently mounted at root paths such as
`/health`, `/inventories`, and `/cards/search` instead of `/api/...`.

With the current docs and example proxy config, a browser request such as
`GET /api/inventories` is forwarded to the backend as `/api/inventories`,
which does not match the current route surface. The frontend can work around
this with a proxy rewrite, but that rewrite is not part of the published
contract today.

Endpoint involved:

All current demo API routes, especially:

- `GET /health`
- `GET /inventories`
- `POST /inventories`
- `GET /cards/search`
- `GET /inventories/{inventory_slug}/items`
- `POST /inventories/{inventory_slug}/items`
- `PATCH /inventories/{inventory_slug}/items/{item_id}`
- `DELETE /inventories/{inventory_slug}/items/{item_id}`
- `GET /inventories/{inventory_slug}/audit`

Current behavior:

- Frontend docs and env guidance point browser clients at `/api`
- The demo backend currently serves root-mounted routes without an `/api`
  prefix
- A request such as `GET /api/inventories` currently misses the documented
  route surface and returns `404 Not Found`

Requested change:

Add `/api`-prefixed aliases for the existing demo API routes so browser-based
frontends can use `FRONTEND_API_BASE_URL=/api` without a custom proxy rewrite.

Preferred behavior:

- `GET /api/inventories` should behave the same as `GET /inventories`
- `GET /api/cards/search` should behave the same as `GET /cards/search`
- The remaining inventory item and audit routes should have the same `/api`
  compatibility
- Existing root-mounted routes should keep working for now as compatibility
  aliases unless there is a strong reason to remove them

If this request is accepted, please also update the frontend-facing contract
artifacts so the published contract stays aligned:

- `docs/api_v1_contract.md`
- `docs/frontend_handoff.md`
- `contracts/openapi.json`
- `contracts/demo_payloads/` if example references need refresh

Example request JSON:

`GET /api/inventories` has no request body.

Example response JSON:

```json
[
  {
    "slug": "personal",
    "display_name": "Personal Collection",
    "description": "Main demo inventory",
    "item_rows": 42,
    "total_cards": 138
  }
]
```

Expected error cases:

- `404` when the requested resource does not exist on a matched route
- The same `400`, `404`, `409`, `503`, and `500` behaviors already documented
  for the corresponding non-prefixed routes
- Error envelopes for matched API routes should stay consistent with the
  existing API contract

Compatibility note:

Additive. This request extends the demo API to support the documented `/api`
base path without removing the existing root-mounted routes.
