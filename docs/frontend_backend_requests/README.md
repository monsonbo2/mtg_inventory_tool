# Frontend Backend Requests

This folder holds optional supporting specs and historical notes for
frontend-requested backend/API changes.

GitHub issues and pull requests are the only official tracking surface for
status, ownership, priority, and discussion. Use this README as the process
guide and supporting-doc template whenever frontend work needs to ask for a
backend contract change.

## Tracking Policy

- Open or update a GitHub issue using
  `.github/ISSUE_TEMPLATE/frontend-backend-request.yml`.
- Open the GitHub issue first and keep status, ownership, priority, discussion,
  implementation progress, and closure there.
- If extra contract detail or examples are helpful, create or update a
  supporting markdown doc in this folder.
- If a supporting doc exists, link it from the GitHub issue.
- Do not track status, owner, implementation PR state, or “last updated” data
  in this folder. Keep that live state in GitHub only.

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
# Frontend Backend Request: Short Title

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

- Put each concrete supporting doc in its own markdown file in this folder.
- Use a short descriptive filename such as:
  - `api_base_path_compatibility.md`
  - `patch_operation_contract_clarity.md`
- Keep each doc concrete and contract-focused.
- Do not add local status, owner, PR-state, or “last updated” metadata.
- Do not maintain a local issue index or local state mirror in this folder.
- Use GitHub issues and PRs for all live tracking updates.

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

For each frontend-to-backend request:

1. Open a GitHub issue using:
   `.github/ISSUE_TEMPLATE/frontend-backend-request.yml`
2. If helpful, create or update a supporting markdown file in this folder.
3. Link the supporting doc from the issue when both exist.

The important thing is to keep the request concrete and contract-focused.

## Recommended Tracking Flow

For each new request:

1. Open the GitHub issue first.
2. Add or update a supporting doc only when extra contract detail is useful.
3. Keep status, ownership, discussion, implementation links, and closure in
   GitHub.
4. Do not update local docs just to mirror ticket state changes.
