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
- `catalog.py`
  Local catalog search and printing resolution.
- `mutations.py`
  Inventory write operations such as add/edit/split/merge/remove.
- `analysis.py`
  Inventory reads, valuation, health checks, report assembly, and export prep.
- `csv_import.py`
  CSV ingest orchestration for inventory imports.
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
- The JSON and error contract is documented in `api_v1_contract.md`, but
  broader deployment guarantees are still limited.
- Dedicated follow-up passes are still required before broader deployment.

The next API-hardening steps are:

- real auth and audit attribution for shared use
- broader deployment policy decisions such as CORS/base-path/topology

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

Two modules still exist primarily for compatibility and entrypoint stability:

- `mvp_importer.py`
- `personal_inventory_cli.py`

They are thinner than the older pre-split structure, but they still expose more
legacy surface than an ideal long-term architecture would.

## Current Pressure Points

The repo is in a good structural place for the next phase of work, but a few
files are still the obvious growth pressure points:

- `cli/inventory.py`
- `inventory/mutations.py`
- `inventory/analysis.py`
- `inventory/report_formatters.py`

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
