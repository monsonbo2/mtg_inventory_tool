# ROADMAP.md

Historical roadmap context for this repo.

GitHub issues and pull requests are the only active work-tracking surface.
This file is meant to be easy-to-find background context for recent branch
milestones, current review context, and the next likely work sequence. It may
drift between commits, so treat GitHub as the source of truth for live ticket
status and ownership.

## Current Checkpoint

Last refreshed: `2026-04-14`

Current review branch:

- `database-sync-optimization`

Open review PR:

- `#42` `Optimize database sync and smooth demo setup`
- <https://github.com/monsonbo2/mtg_inventory_tool/pull/42>

Mainline assumption:

- `origin/HEAD` still points to `origin/master`

## What Recently Landed On The Review Branch

Sync and importer work:

- sync run, step, artifact, and issue bookkeeping
- split sync commands:
  - `sync-scryfall`
  - `sync-identifiers`
  - `sync-prices`
- unchanged-artifact skip behavior for sync/import runs
- streamed MTGJSON identifier and price payload reads
- importer timing and sync-history visibility
- Scryfall metadata caching and safer validator reuse
- search-index maintenance commands:
  - `check-search-index`
  - `rebuild-search-index`
  - `list-sync-runs`
  - `show-sync-run --run-id ...`

Important performance result:

- narrowing the `mtg_cards` FTS update trigger removed the main bulk identifier
  import bottleneck
- on the benchmark harness, `import-identifiers` dropped from effectively
  `13m+` to about `12.8s`

Frontend/demo work:

- frontend demo launchers now prefer the repo-local `.venv/bin/python`
- `frontend/` now has first-class:
  - `npm run demo:bootstrap`
  - `npm run backend:demo`
- the demo bootstrap output and docs now point people to repo-local launchers
  instead of a global `mtg-web-api` wrapper
- full-catalog demo bootstrap now optionally supports real MTGJSON pricing when
  both `--identifiers-json` and `--prices-json` are supplied alongside
  `--scryfall-json`

Recent commits worth knowing:

- `213b7d6` `Smooth frontend demo setup flow`
- `3cccf81` `Add priced full-catalog demo bootstrap`

## Current Validation Snapshot

Last known green checks on the review branch:

- `PYTHONPATH=src ./.venv/bin/python -m unittest discover -s tests -q`
  - `391` passed, `75` skipped
- `cd frontend && npm run test`
  - `67` passed
- `cd frontend && npm run build`
  - passed
- full-catalog priced demo bootstrap via npm
  - passed with local fixture files

## Recommended Next Issue Sequence

If work resumes after PR `#42`, the best next sequence is:

1. `#43` Shared-service onboarding-state contract clarity
2. `#45` Shared-service validation fixtures for permission-aware frontend states
3. `#44` Proxy-backed shared-service validation harness for `/api` rollout
4. `#38` Optimize grouped name search latency on full-catalog demo DB
5. Re-scope `#39` Local-first bootstrap and lightweight printing lookup support
6. `#41` Support bulk inventory mutations across all filtered rows

Why this order:

- `#43` is likely the cheapest high-value shared-service issue
- `#45` turns shared-service permission states into something repeatable
- `#44` becomes much easier and more useful once those fixtures exist
- `#38` is the sharpest remaining product-feel / demo-latency issue
- `#39` is partly stale relative to the current code and should be narrowed
  before more backend work is added
- `#41` is the largest remaining feature contract and should follow the smaller
  shared-service and demo-readiness wins

## Open Issue Notes

### `#43` Shared-service onboarding-state contract clarity

Best first approach:

- add a small machine-readable status route such as `/me/access-summary`
- keep it focused on:
  - `can_bootstrap`
  - `has_readable_inventory`
  - `visible_inventory_count`
  - `default_inventory_slug`
- document the frontend decision tree against that route

Reasonable alternative:

- docs-only decision tree using current `GET /inventories` plus
  `POST /me/bootstrap`

Why the route is preferred:

- the frontend currently has to infer too much from multiple endpoints and
  permission failures

### `#45` Shared-service validation fixtures

Best first approach:

- add a scripted fixture bootstrap that seeds:
  - one bootstrap-eligible editor
  - one authenticated user with no memberships
  - one read-only inventory member
  - one write-capable member
  - one global admin
- publish the expected verified headers and visible inventory outcomes

Reasonable alternative:

- commit a prebuilt SQLite fixture DB

Why the scripted fixture is preferred:

- it survives migrations better and is easier to reason about than a binary DB
  snapshot

### `#44` Proxy-backed shared-service validation harness

Best first approach:

- add a lightweight committed reverse-proxy config for the exact `/api`
  deployment shape
- add a smoke-test path that validates:
  - `/api` prefix stripping
  - verified header injection
  - denied client-supplied auth headers
  - same-origin request behavior

Reasonable alternative:

- simulate the proxy in an in-process ASGI test harness

Why the real proxy shape is preferred:

- the issue is about rollout validation, not only backend unit correctness

### `#38` Grouped name search latency

Best first approach:

- remove or sharply constrain the broad grouped-search substring fallback
- rely on FTS plus exact/prefix ordering for the normal path
- add benchmark coverage so future regressions are obvious

Reasonable alternative:

- build a dedicated grouped-name index keyed by `oracle_id`

Why the tactical query fix is preferred first:

- it is the likely first speed win with the lowest schema complexity

### `#39` Local-first bootstrap and lightweight printing lookup support

Current caution:

- parts of the original issue are already partially satisfied by current code:
  - `/me/bootstrap` is already idempotent
  - printing lookup already defaults to an English-first subset and only loads
    all languages on demand

Best first approach:

- re-scope or split the issue before implementation
- keep only the work that is still actually missing

Reasonable alternative:

- add a lighter-weight printing summary route immediately

Why re-scoping is preferred:

- this issue is at risk of duplicating behavior the repo now already has

### `#41` Filter-based bulk mutations

Best first approach:

- extend the existing bulk route to support a selection envelope
  - explicit `item_ids`
  - or backend-owned filters matching the inventory list route semantics
- resolve the filtered selection inside the same transaction
- return transfer-style summaries for large operations rather than giant ID
  payloads

Reasonable alternative:

- add a sibling route such as `/items/bulk-filtered`

Why the additive selection envelope is preferred:

- it keeps one long-term bulk contract instead of splitting closely related
  behavior across multiple endpoints

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
