# Frontend Backend Requests

This document defines how frontend work should request backend/API changes
without directly editing backend implementation code.

## Purpose

Use this process when the frontend sandbox hits a real backend limitation:

- a missing endpoint
- a missing field in an existing response
- a missing write flow
- an unclear error contract
- an integration problem that should be solved in the API instead of the UI

Do not use this process for purely presentational or UI-only choices.

## Rule Of Thumb

Open a backend request when:

- the frontend cannot complete a planned screen or interaction using the
  documented API contract
- the frontend would otherwise need to duplicate backend business logic
- the OpenAPI contract or demo payloads appear incomplete or misleading

Do not open a backend request when:

- the issue is only styling, layout, animation, copy, or client-side state
- the API already supports the flow and the problem is only in the frontend
  implementation

## Required Request Format

Each frontend-to-backend request should include:

1. Feature or screen
   Example: `Inventory table quick edit`

2. Current blocker
   What exactly cannot be built or what is ambiguous?

3. Endpoint involved
   Example: `PATCH /inventories/{inventory_slug}/items/{item_id}`

4. Current behavior
   What the API returns today, including example payloads if helpful

5. Requested change
   Be concrete about the desired field, route, or contract behavior

6. Example request and response
   Small JSON examples are preferred

7. Expected error cases
   Example: `400` validation, `404` not found, `409` conflict

8. Compatibility note
   Say whether the request is:
   - additive
   - behavior-changing
   - potentially breaking

## Suggested Template

```md
## Frontend Backend Request

Feature / screen:

Current blocker:

Endpoint involved:

Current behavior:

Requested change:

Example request JSON:

Example response JSON:

Expected error cases:

Compatibility note:
```

## Review Expectations

- Frontend contributors should not directly modify backend files under
  `src/mtg_source_stack/`.
- Accepted backend changes should update the relevant contract artifacts:
  - `docs/api_v1_contract.md`
  - `contracts/openapi.json`
  - `contracts/demo_payloads/` when useful
- Backend changes should be reviewed against the API contract first, not only
  against UI convenience.

## Where To Put Requests

Until a dedicated issue template exists, put frontend backend requests in:

- the PR description for the frontend branch, or
- a GitHub issue referencing the affected screen/flow, or
- a short written request shared with the backend owner using the template
  above

The important thing is to keep the request concrete and contract-focused.
