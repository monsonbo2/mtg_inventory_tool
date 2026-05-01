# Architecture

This document describes the current runtime structure of the repo as it exists
today.

For the docs index and recommended reading order, start with `docs/README.md`.

It is the best high-level orientation doc for contributors who want to
understand where code lives before diving into implementation details.

For backend product rules and schema scope, see `backend_v1_contract.md`.
For HTTP-facing JSON and error semantics, see `api_v1_contract.md`.

## Current Package Boundaries

The installable package lives under `src/mtg_source_stack/`.

Top-level runtime areas:

- `api/`
  FastAPI shell, request lifecycle, and HTTP route wiring for the current
  backend contract. It supports a default `local_demo` runtime mode plus a
  safer `shared_service` startup mode, and now aligns its route boundary with
  the current synchronous inventory and SQLite-backed service layer.
- `cli/`
  Thin command-line entrypoints and argument parsing.
- `db/`
  SQLite connection setup, migrations, schema readiness, and snapshots.
- `importer/`
  Bulk ingest and sync logic for Scryfall and MTGJSON.
- `inventory/`
  Core inventory domain logic, reporting, serialization, and audit helpers.

Supporting top-level modules:

- `errors.py`
  Shared domain error vocabulary used by app-facing services.
- `api_contract.py`
  Framework-agnostic JSON/error mapping helpers used by the current demo API
  shell and broader HTTP contract work.
- `pricing.py`
  Small shared pricing constants.
- `mvp_importer.py`
  Legacy importer-facing wrapper module.
- `personal_inventory_cli.py`
  Legacy inventory-facing wrapper module.

## Inventory Package Shape

`inventory/` is the most important domain package.

The main modules are:

- `service.py`
  Intentional public inventory-domain facade used by the CLI and intended to
  remain the stable inventory service surface for future app work.
- `inventories.py`
  Inventory container creation and listing.
- `owned_items.py`
  Concrete owned-row read, paging, sorting, and table-shaping logic.
- `reporting.py`
  Concrete export, health, duplicate-group, and report assembly logic.
- `valuation.py`
  Concrete valuation, price-gap, and reconciliation logic.
- `analysis.py`
  Compatibility facade that preserves the older reporting/read import surface
  while delegating to `owned_items.py`, `reporting.py`, and `valuation.py`.
- `catalog.py`
  Compatibility facade for older catalog imports.
- `catalog_search.py`
  Concrete local catalog search and grouped-name lookup logic.
- `catalog_printings.py`
  Concrete printing list/summary lookup and default-printing ranking logic.
- `catalog_resolution.py`
  Concrete default-add and exact-printing resolution logic.
- `mutations.py`
  Compatibility facade for older inventory write-operation imports.
- `operations/`
  Concrete inventory write-operation modules, including add, bulk, identity,
  item-update, and row-lifecycle flows.
- `csv_import.py`
  CSV ingest orchestration for inventory imports.
- `import_engine.py`
  Shared pending-row validation and commit engine used across import flows.
- `csv_formats.py`
  Source-specific CSV adapter detection and normalization before import.
- `decklist_import.py`
  Pasted decklist parsing plus preview/commit planning for decklist imports.
- `deck_url_import.py`
  Public remote deck URL import facade.
- `remote_deck_sources.py`
  Remote fetch transport, redirect safety, and snapshot-token helpers.
- `remote_deck_providers.py`
  Provider-specific URL parsing and payload/page parsing for remote deck
  imports.
- `remote_deck_planning.py`
  Remote deck preview, resolution, and commit planning logic.
- `export_profiles.py`
  Profile registry for HTTP and CLI CSV exports.
- `import_resolution.py`
  Shared structured ambiguity-resolution models and option shaping for import
  preview flows.
- `import_summary.py`
  Shared import summary helpers for preview/commit responses.
- `audit.py`
  Transactional audit logging for inventory mutations.
- `response_models.py`
  Typed service models and JSON-oriented serialization.
- `money.py`
  Decimal parsing, coercion, and formatting helpers.
- `normalize.py`
  Shared normalization and text/tag/finish helpers.
- `policies.py`
  Business rules for row identity and acquisition merge behavior.

Internal query/report helper modules:

- `query_catalog.py`
- `query_inventory.py`
- `query_pricing.py`
- `query_reporting.py`
- `report_formatters.py`
- `report_helpers.py`
- `report_io.py`

## Intentional Public Surface

The current intended public runtime surface is:

- CLI entrypoints in `cli/`
- API shell in `api/`
- importer wrapper module `mvp_importer.py`
- inventory wrapper module `personal_inventory_cli.py`
- inventory domain facade `inventory/service.py`
- compatibility facades `inventory/analysis.py`, `inventory/catalog.py`,
  `inventory/mutations.py`, and `inventory/deck_url_import.py` for existing
  callers that still import those modules directly

The concrete `query_*` and `report_*` modules are internal organization
modules. They are real sources of truth for implementation, but they are not
intended as broad public compatibility layers.

The older `inventory/reports.py` and `inventory/queries.py` facades have been
retired.

## Current API Posture

The `api/` package should currently be understood as a local-first web layer
with an incremental shared-service posture, not a fully production-hardened
shared service.

- `local_demo` remains the default runtime mode for local UI and contract work.
- `shared_service` is available for pre-migrated, single-host SQLite
  deployments and disables auto-migrate by default.
- The route surface is stable enough for local/demo UI work and modest shared
  use.
- The API now uses sync route handlers to match the current synchronous
  inventory services and SQLite access.
- In `shared_service`, the current access model now has two layers:
  - global proxy-backed app roles: `editor`, `admin`
  - local inventory membership roles: `viewer`, `editor`, `owner`
- Inventory listing, inventory reads, and inventory writes are now scoped by
  local memberships, with global `admin` as the bypass.
- Inventory table reads now have both a legacy array route and a paginated
  envelope route for server-side filtering, sorting, and table paging.
- Inventory owners and global admins can manage local memberships over the API;
  the backend preserves at least one owner and audits grant, role-change, and
  revoke actions.
- Inventory creation is available to authenticated users, and the creator
  becomes `owner` on the new inventory.
- First-run shared-service onboarding can now use `POST /me/bootstrap` to
  create one owned personal `Collection` inventory for an authenticated user.
- The recommended first-live deployment is same-origin through a reverse proxy
  that publishes `/api`, strips that prefix before forwarding, and injects
  verified identity headers.
- The shared-service SQLite posture now relies on the central connection layer
  enabling WAL, busy-timeout, `synchronous=NORMAL`, and tested snapshot-based
  recovery.
- The JSON and error contract is documented in `api_v1_contract.md`, but
  broader deployment guarantees are still limited.
- Dedicated follow-up passes are still required before broader deployment.

The next API-hardening steps are:

- rollout validation against the real proxy/header/membership deployment shape
- clearer admin-only route policy for shared use
- observability and operator automation for the shared-service deployment

## Frontend Collaboration Boundary

The repo now also carries a non-runtime frontend sandbox boundary:

- `frontend/`
  Reserved UI workspace. Frontend implementation should stay inside this tree.
- `contracts/openapi.json`
  Snapshot of the current demo API contract for client generation and review.
- `contracts/demo_payloads/`
  Example JSON payloads that mirror the shapes the UI should handle.
- `docs/frontend_handoff.md`
  Working agreement for how frontend and backend changes should be coordinated.

The intended boundary is HTTP-only. Frontend code should not reach into the
Python runtime packages for business logic or direct data access.

## Legacy / Compatibility Areas

The main compatibility seams are now explicit and intentionally thin:

- `mvp_importer.py`
- `personal_inventory_cli.py`
- `inventory/analysis.py`
- `inventory/catalog.py`
- `inventory/mutations.py`
- `inventory/deck_url_import.py`

The preferred service-entry surface is still `inventory/service.py`, but the
compatibility modules remain in place so existing scripts, notebooks, and
callers do not need to move all at once.

## Current Pressure Points

The repo is in a good structural place for the next phase of work, but a few
files are still the obvious growth pressure points:

- `cli/inventory.py`
- `inventory/operations/bulk.py`
- `inventory/remote_deck_providers.py`
- `inventory/report_formatters.py`
- `inventory/transfer.py`

Those modules are not broken, but they are the first ones likely to need
further decomposition if the web app or reporting surface expands.

## Deferred Structural Work

The repo is not currently pursuing a larger package split such as
`collection/`, `reference_data/`, and `reporting/`.

That may still make sense in the future, especially if:

- the web backend grows substantially
- multiple contributors are working in parallel
- importer, reporting, and app-service concerns expand further

For now, the current `db / importer / inventory / cli` structure is the stable
base to document and build on.
