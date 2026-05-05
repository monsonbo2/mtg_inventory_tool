# ROADMAP.md

Historical roadmap context for this repo.

GitHub issues and pull requests are the only active work-tracking surface.
This file is meant to be easy-to-find background context for recent branch
milestones, current review context, and the next likely work sequence. It may
drift between commits, so treat GitHub as the source of truth for live ticket
status and ownership.

## Current Checkpoint

Last refreshed: `2026-04-29`

This checkpoint was refreshed from the local repo state. GitHub remains the
source of truth for live issue state, PR status, and ownership.

Current local branch:

- `issue/47-split-backend-modules`

Current reviewed base:

- `9a08ed9` / `origin/master`

Most recent local commit:

- `39fa272` / `Replace CLI star import with explicit shim exports`

Current branch focus:

- finish the `#47` backend module split with explicit public surfaces and doc
  cleanup
- keep the compatibility facades stable while documenting the new concrete
  module layout underneath them
- avoid starting a second broad refactor unless one of the new concrete
  hotspots grows again

Open review PR:

- none currently

Open GitHub issues:

- `#72` Aggregate public inventory share rows by visible identity
- `#70` Allow viewer copy-out and export for readable inventories
- `#57` Future work: production reverse-proxy path for shared-service rollout
- `#52` Frontend: complete owner-managed read-only inventory sharing links
- `#47` Break up oversized backend modules before more feature work lands
- `#41` Support bulk inventory mutations across all filtered rows

Local structural status:

- the shared import engine split is in place
- inventory write operations now live under `inventory/operations/`
- API routes now live under `api/routes/` by route family
- inventory reads/reporting now live under `owned_items.py`, `reporting.py`,
  and `valuation.py`, with `analysis.py` kept as a compatibility facade
- remote deck URL imports now split transport, provider parsing, and planning
  across `remote_deck_sources.py`, `remote_deck_providers.py`, and
  `remote_deck_planning.py`
- catalog logic now splits across `catalog_search.py`,
  `catalog_printings.py`, and `catalog_resolution.py`, with `catalog.py` kept
  as a compatibility facade
- the remaining local follow-through is documentation, explicit surface
  declarations, and small cleanup rather than another large structural slice

Readiness summary:

- demo readiness: controlled-demo ready for the core happy path after the
  frontend-refinement merge
- small rollout readiness: conditionally ready for a trusted 10-15 person pilot
  only after the real proxy, backup/restore, membership, and browser-session
  checks below are rehearsed on the target host
- not ready for broader shared use, direct API exposure, separate-origin CORS,
  or an unmanaged "open it and see what happens" rollout
- share-link UI/public-page, browser export, duplicate UI, transfer dry-run,
  and ambiguous import resolution should be framed as incomplete or API-only
  unless they are explicitly added to the demo story

## Current Validation Snapshot

Last known green checks from the post-merge readiness review:

- `PATH=.venv/bin:$PATH ./scripts/test_backend.sh` with localhost socket
  binding allowed
  - `440` tests ran, `OK`, `0` skipped
- `PATH=.venv/bin:$PATH ./scripts/test_backend_web.sh` with localhost socket
  binding allowed
  - `113` tests ran, `OK`, `0` skipped
- `cd frontend && npm test`
  - `75` passed
- `cd frontend && npm run build`
  - production build passed
- `cd frontend && npm run demo:bootstrap -- --force --shared-service-fixtures`
  - shared-service fixture DB bootstrap passed
- `cd frontend && npm run smoke:shared-service-proxy -- --start-backend` with
  localhost socket binding allowed
  - passed when localhost socket binding was allowed
  - verified `/api` prefix stripping, static frontend serving, spoofed auth
    header stripping, fixture identity injection, expected visible inventories,
    readable-user search, and no-access search denial
- `cd frontend && npm run demo:bootstrap -- --force --shared-service-fixtures --full-catalog ...`
  - historical full-catalog shared-service demo DB bootstrapped at
    `var/db/frontend_demo_full.db`
  - imported `113776` Scryfall cards, `113774` MTGJSON identifier links, and
    `558116` MTGJSON price snapshots
- historical shared-service full-catalog demo served through the local proxy
  harness
  - backend: `http://127.0.0.1:8000`
  - browser URL: `http://127.0.0.1:5174`
  - fixture identity: `writer@example.com`
  - proxy checks: `/api/health` returned `200`; static frontend returned `200`
  - rough full-catalog API search timings through the proxy:
    - `Cloud`: `0.125s`
    - `Clou`: `0.121s`
    - `Lightning`: `0.124s`
    - `Sol`: `0.170s`
- `cd frontend && npm audit --omit=dev`
  - `0` production vulnerabilities
- `cd frontend && npm audit`
  - `5` moderate dev-only findings through the Vite/esbuild toolchain

Important validation caveat:

- The default sandbox can block localhost socket binding. If backend/API or
  proxy tests skip unexpectedly, rerun them in an environment that can bind
  `127.0.0.1` ephemeral ports.

## Highest Priority Follow-Ups

### 1. Demo Scope Closure And Issue Cleanup

The core happy-path demo is ready. The biggest near-term planning task is to
decide whether the next demo stays on that core path or expands into features
that are currently incomplete in the browser.

Needed:

- keep the first demo focused on:
  - inventory selection
  - card search and autocomplete
  - quick add
  - compact browse and table views
  - quick edits
  - selected-row, filtered, and whole-collection bulk edits
  - selected-row copy/move as a writable user
  - audit drawer
- if viewer copy/export is part of the story, finish or re-scope `#70`:
  - copy source eligibility should follow readable source access
  - move source eligibility should require writable source access
  - destination choices should use `can_transfer_to`
  - browser CSV export still needs a UI affordance if it is demo-visible
- if public share links are part of the story, finish `#72` and `#52` first
- leave ambiguous import resolution, duplicate inventory UI, and transfer
  dry-run preview out of the first demo unless explicitly framed as API-only

Why:

- the merged frontend can support a strong controlled demo, but the open issue
  tracker still contains product surfaces that should not be implied as done
- the roadmap previously listed closed issue dependencies as blockers; GitHub is
  now the source of truth for live issue state

### 2. Production Reverse Proxy Runbook (`#57`)

This is the biggest blocker for even a small real rollout.

Needed:

- commit or document the exact production proxy config for the supported shape:
  same origin, frontend static assets, `/api` prefix stripping, backend on
  loopback or a private interface
- strip client-supplied `X-Authenticated-User`, `X-Authenticated-Roles`, and
  `X-Actor-Id`
- inject verified `X-Authenticated-User`
- optionally inject normalized `X-Authenticated-Roles`
- allow unauthenticated public share reads only for the documented
  `/api/shared/inventories/{share_token}` route while still stripping spoofed
  identity headers
- document TLS termination, backend bind address, process startup, log capture,
  restart, and rollback commands

Why:

- shared-service auth is only safe behind a trustworthy identity-injecting
  proxy
- exposing `mtg-web-api` directly would let clients spoof trusted headers

### 3. First-Live Backup And Restore Rehearsal

Needed:

- create a backup/snapshot of the candidate rollout DB
- restore it into a fresh DB path
- start `mtg-web-api` in `shared_service` against the restored DB
- verify schema readiness, search, reads, writes, audit attribution, and request
  IDs
- record the rollback command sequence in the deployment notes

Why:

- SQLite is acceptable for this pilot only if recovery is practiced, not merely
  documented
- bulk imports, bad membership grants, or mistaken write actions need a clear
  recovery path

### 4. Real User Permission Rehearsal

Needed:

- seed the actual pilot users and inventory memberships
- verify at least two real browser identities before launch:
  - viewer can read but receives `403` on writes
  - editor/owner can read and write
  - no-access user sees the access-needed state and cannot search
  - admin can see expected inventories only when the proxy injects `admin`
- verify audit entries show the verified user identity, not `local-demo`

Why:

- the fixture harness is green, but the real IdP/proxy/header path is the
  launch-critical integration
- membership management is currently CLI-first, so operator mistakes are likely

### 5. Public Share-Link Completion (`#52`, `#72`)

Needed:

- aggregate public share rows by the fields visible in the public response:
  `scryfall_id`, `condition_code`, `finish`, and `language_code`
- keep public payloads free of private fields such as item IDs, location, tags,
  notes, acquisition fields, and pricing
- add owner/admin sharing controls in the inventory UI:
  status, create, copy active link, rotate, and revoke
- add the anonymous public inventory page at
  `/shared/inventories/{share_token}`
- have the public page fetch JSON through
  `/api/shared/inventories/{share_token}` in shared-service deployments
- handle loading, empty, revoked/not-found, and permission-denied states

Why:

- backend share-link routes exist, but the browser experience is not complete
- `#72` is a backend projection issue that can make public rows look duplicated
  because the fields that distinguish private rows are intentionally hidden

### 6. Viewer Copy-Out And Browser Export Completion (`#70`)

Needed:

- verify the frontend treats `can_transfer_to` as a destination capability, not
  as a source-copy requirement
- allow copy controls when the source inventory is readable and the target is
  writable/transferable
- keep move controls gated on writable source plus writable/transferable target
- add a CSV export UI if readable-inventory export should be demo-visible
- close or update `#70` once the remaining frontend scope is confirmed

Why:

- the backend authorization and API tests are in place after PR `#73`
- the remaining issue comment calls out browser-side capability behavior and
  export visibility

### 7. Frontend Import Resolution UX

Needed:

- build the frontend preview/resolution flow for CSV, pasted decklists, and
  deck URL imports
- preserve and resubmit `source_snapshot_token` for deck URL preview/commit
- show ambiguous rows, finish-required rows, and selected resolution options
- keep current direct-commit behavior for imports that are already
  `ready_to_commit`

Why:

- the backend supports preview/commit and resolutions, but the frontend
  currently stops when `resolution_issues` are returned
- this is acceptable for a scripted demo only if the demo avoids ambiguous
  imports

Blocked / needs backend confirmation:

- verify exact preview/commit behavior with real ambiguous examples before
  building the full resolver UI
- deck URL resolution must preserve and resubmit `source_snapshot_token`

### 8. Surface Or Explicitly De-Scope Backend-Only API Features

Needed:

- decide which of these should be demo-visible now:
  - CSV export download
  - duplicate inventory
  - owner-managed public share links
  - transfer dry-run preview
- either add UI affordances for chosen features or update demo docs so they are
  clearly backend/API capabilities, not current frontend workflow promises

Why:

- the API wrappers or backend routes exist, but several are not visible in the
  app
- demo expectations should match what the browser can actually do

### 9. Frontend Work That Can Proceed Now

These workstreams are no longer blocked by the previously tracked capability,
pagination, and membership API slices, but some are still product-scope
decisions for the next demo.

Recommended order:

1. full-catalog browser polish
2. Playwright smoke coverage for the shared-service fixture modes
3. viewer copy/export polish if `#70` remains in demo scope
4. public share-link UI and public page if `#52` is in demo scope
5. CSV export UI
6. duplicate inventory UI
7. transfer dry-run preview

Details:

- full-catalog browser polish
  - tune search/autocomplete perceived latency
  - review Scryfall image loading and fallback states
  - tighten table density and readability
  - verify mobile layout
  - sanity-check valuation display with imported MTGJSON prices
  - reduce decorative weight where it gets in the way of repeated inventory use
- CSV export UI
  - use the existing `exportInventoryCsv(...)` wrapper
  - add a collection/table export action with basic provider/profile/filter
    options
  - download using the filename returned in `Content-Disposition`
- duplicate inventory UI
  - use the existing `duplicateInventory(...)` wrapper
  - add a collection-level action with target name, slug, and optional
    description
  - refresh inventory summaries and select the duplicate after success
- transfer dry-run preview
  - use the existing transfer API with `dry_run: true`
  - show would-copy / would-move / would-merge / would-fail counts before
    committing
  - keep the current direct transfer path only as the final commit action
- Playwright smoke coverage
  - cover writer, viewer, no-access, and admin fixture modes
  - cover add/edit/remove, table selection, bulk actions, copy/move, mobile
    layout, full-catalog search, and image behavior
- viewer copy/export polish
  - align source and destination gating with `can_read`, `can_write`, and
    `can_transfer_to`
  - expose CSV export only if it belongs in the browser demo
- public share-link UI
  - backend routes already exist for status/create/rotate/revoke and public
    JSON reads
  - also needs the public page and `#72` row aggregation before being presented
    as a complete public-sharing story
  - should be skipped if share links are not part of the near-term demo story

Do not start yet:

- full import resolution UI until the ambiguous preview/commit behavior is
  verified against realistic examples
- broad organization/team administration UI until there is a deliberate product
  story for it

### 10. Full-Catalog Browser UX Pass

Done:

- bootstrapped a full-catalog shared-service demo DB from current Scryfall
  default cards
- imported MTGJSON identifiers and prices for realistic valuation data
- ran rough API search checks through the local proxy harness:
  - `Cloud`
  - `Clou`
  - `Lightning`
  - `Sol`

Still needed:

- run a browser-driven pass against the full-catalog demo for:
  - search/autocomplete perceived latency
  - image loading behavior from Scryfall URLs
  - inventory table responsiveness with real card metadata
  - valuation display sanity with imported MTGJSON prices
- capture any UX latency issues that do not show up in API-only timings

Why:

- the default demo DB is intentionally tiny and does not prove realistic search
  behavior
- API timings are now reassuring, but browser rendering, remote card images,
  and dense-table behavior still need human-facing review

### 11. Minimal Pilot Ops Checklist

Needed:

- write a short operator checklist covering:
  - install/runtime versions
  - env vars, especially `MTG_API_SNAPSHOT_SIGNING_SECRET`
  - migration command
  - Scryfall/MTGJSON refresh command and timing
  - backend start command
  - frontend build/deploy command
  - proxy reload command
  - backup and restore commands
  - membership grant/list/revoke commands
  - smoke checks after deploy
- explicitly warn not to run `sync-bulk`, `import-all`, or large updates during
  active editing windows

Why:

- the repo has enough pieces for a small pilot, but the operational sequence is
  still spread across docs and scripts

### 12. Dependency And Packaging Tightening

Needed:

- add a reproducible Python dependency story for the web stack:
  constraints file, lock file, or documented pinned install process
- update the Vite/esbuild toolchain when a non-breaking fix path is available,
  or document that current audit findings are dev-server-only
- decide whether to add a committed deployment artifact such as systemd,
  Caddy/nginx config, or container/compose files

Why:

- production dependency audit is clean, but the Python web dependency versions
  are currently range-based
- dev-only audit findings should not be allowed to become background noise

### 13. General Backlog (`#41`, `#47`)

Needed:

- add first-class filtered-row bulk mutation support instead of relying only on
  selected explicit item IDs (`#41`)
- break up at least one oversized backend module along a clean boundary before
  piling on another large feature wave (`#47`)

Why:

- `#41` is the product-grade answer for applying edits to the current filtered
  result set
- `#47` is not demo-critical, but it lowers the cost and risk of the next
  backend changes

## Demo Guidance

Recommended demo path:

1. Bootstrap the demo DB with shared-service fixtures.
2. Build the frontend.
3. Run the shared-service proxy smoke test.
4. Demo as a user with readable/writeable inventory access.
5. Stay on:
   - inventory selection
   - card search and autocomplete
   - quick add
   - compact browse and table views
   - quick edits
   - bulk edit on a small selection or filtered table view
   - copy/move selected rows
   - audit drawer

Avoid in a first demo unless specifically framed as incomplete or API-only:

- ambiguous import resolution
- owner-managed share-link UI
- CSV export from the browser
- duplicate inventory from the browser
- real organization/team administration
- separate-origin browser API access

## Small Pilot Guidance

Acceptable pilot shape:

- 10-15 trusted users
- one host
- one reverse proxy
- one `mtg-web-api` process
- one SQLite database on local disk
- same-origin frontend/backend
- intentional membership grants
- no large admin import/sync jobs during active editing windows

Do not pilot yet if any of these are missing:

- real proxy header stripping and injection has not been tested
- backup restore has not been rehearsed
- user memberships have not been listed and checked
- at least two real browser identities have not been verified
- operator cannot quickly identify logs and request IDs for a failed action

## Current Working Assumptions

- stay local-first and SQLite-first for now
- treat `shared_service` as a modest single-host rollout shape, not a
  horizontally scaled SaaS target
- keep demo/bootstrap tooling as part of the supported developer experience, not
  as throwaway scripts
- prefer GitHub issues / PRs for live tracking, and use this file only as
  quickly discoverable planning context

## First Places To Look When This File Drifts

1. `git status --short --branch`
2. recent commits on the active branch
3. open GitHub issues and pull requests
4. the current PR description if a review branch is already open
