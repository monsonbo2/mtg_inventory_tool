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

## Demo Scope

The current intended demo surface is:

- inventory selector
- card search
- add card flow
- owned rows table
- quick edit for quantity, finish, location, notes, and tags
- recent audit activity

## Local Dev Flow

1. Start the backend locally:

   ```bash
   pip install -e .[web]
   mtg-web-api --db var/db/mtg_mvp.db
   ```

2. Point the frontend at the local API base URL.
3. Build against the published HTTP contract rather than backend internals.

## Working Rules

- Frontend changes stay inside `frontend/` unless you explicitly request a
  backend contract change.
- Backend changes should be requested as API-contract work, not merged in as
  opportunistic UI edits.
- The frontend may do UX validation, but backend validation remains the source
  of truth.
- `X-Actor-Id` is ignored by default by the API shell. Audit writes will appear
  as `local-demo` unless trusted-header mode is deliberately enabled.

## Known Limits

- The current API shell is suitable for local/demo use, not shared deployment.
- The backend still uses synchronous SQLite-backed services under the HTTP
  layer.
- Authentication and permissions are not implemented yet.
