# Frontend Backend Requests

This folder is the home for frontend-requested backend/API changes.

Use this README as the process guide and template whenever frontend work needs
to ask for a backend contract change.

## Status Index

Use this table as the lightweight in-repo status board for active frontend
backend requests.

| Request | Issue / PR | Status | Owner | Notes |
| --- | --- | --- | --- | --- |
| `api_base_path_compatibility.md` | _add link_ | Proposed | _unassigned_ | `/api` dev-proxy compatibility |
| `card_image_fields_for_visual_ui.md` | _add link_ | Proposed | _unassigned_ | image-oriented UI fields |
| `expanded_frontend_demo_seed_data.md` | _add link_ | Proposed | _unassigned_ | richer demo bootstrap data |
| `patch_operation_contract_clarity.md` | _add link_ | Proposed | _unassigned_ | patch response semantics |
| `published_value_enums_and_defaults.md` | _add link_ | Proposed | _unassigned_ | stable enums/defaults |

Update this table when a request changes status or gets tied to a GitHub issue
or implementation PR.

### Suggested Status Values

- `Proposed`
- `Triaged`
- `Accepted`
- `In Progress`
- `Done`
- `Blocked`
- `Declined`
- `Superseded`

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

Status: Proposed
Owner: Unassigned
GitHub issue: Not linked yet
Implementation PR: Not linked yet
Last updated: YYYY-MM-DD

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

## How To Use This Folder

- Put each concrete frontend request in its own markdown file in this folder.
- Use a short descriptive filename such as:
  - `api_base_path_compatibility.md`
  - `patch_operation_contract_clarity.md`
- Keep each request concrete and contract-focused.
- Include the metadata header from the template in every request file.
- Keep the status row in the table above in sync with the current GitHub issue
  or PR state.

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

- a markdown file in this folder
- the PR description for the frontend branch, or
- a GitHub issue referencing the affected screen/flow and linking the matching
  request doc

The important thing is to keep the request concrete and contract-focused.

## Recommended Tracking Flow

For each new request:

1. Create or update the markdown file in this folder using the template below.
2. Open a GitHub issue for the request, or record the active PR if the request
   is being handled immediately.
3. Add the issue or PR link to the status table in this README.
4. Update the status value as the request moves from `Proposed` to `Done` or
   another final state.
5. When a request is completed, link the implementation PR or commit in the
   issue/PR column or notes column.
