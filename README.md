# MTG Inventory Tool

A local-first Magic: The Gathering inventory workflow built around SQLite,
Scryfall, and MTGJSON.

Use it to:

- import a local MTG catalog and daily pricing snapshots
- create and maintain one or more personal inventories
- track condition, finish, language, location, tags, notes, and acquisition data
- bulk-edit inventory rows through the API
- copy, move, transfer, and duplicate inventory contents safely through the API
- export reports and CSVs from the local SQLite database
- keep a per-edit audit trail for inventory mutations

## Start Here

If you're new to the repo, read these in order:

1. this README
2. `docs/README.md`
3. `notebooks/00_repo_architecture_walkthrough.ipynb`

If you're planning backend or API work, the live runtime contract starts with
`docs/backend_v1_contract.md`, `docs/ingestion_flow.md`, and
`docs/api_v1_contract.md`.

If you're planning frontend work, start with `docs/frontend_handoff.md`,
`frontend/README.md`, and `contracts/openapi.json`.
Use `docs/frontend_backend_requests/` only when a GitHub issue links to a
supporting spec or historical note. Use the GitHub issue template at
`.github/ISSUE_TEMPLATE/frontend-backend-request.yml` for new frontend backend
requests. GitHub issues and PRs are the only live tracking surface; files under
`docs/frontend_backend_requests/` are optional supporting specs and historical
context, not the authoritative ticket state.

If you want the easiest-to-find snapshot of recent milestones, the current
review branch context, and the likely next work sequence, read `ROADMAP.md`.

## Current Runtime Shape

- The active runtime package lives in `src/mtg_source_stack/`.
- The current entrypoints are `mtg-mvp-importer`, `mtg-personal-inventory`, and
  the optional web shell `mtg-web-api`.
- The FastAPI layer lives in `src/mtg_source_stack/api/` and now supports a
  default `local_demo` mode plus a safer `shared_service` startup mode for
  modest single-host shared use.
- The runtime starts from `src/mtg_source_stack/mtg_mvp_schema.sql` and then
  applies the tracked migrations in `src/mtg_source_stack/db/migrations/`.
- `docs/schema_full.sql` is a future normalized design, not the live runtime
  model.
- Ordinary search, valuation, and reporting commands read from local SQLite
  only.
- `sync-bulk` can fetch fresh upstream bulk files, but normal read paths do not
  call live APIs.
- Pricing imports currently keep USD retail and buylist snapshots only.
- The current API shell now aligns its HTTP route boundary with the existing
  synchronous SQLite-backed service layer. Shared-service identity resolution,
  SQLite WAL/busy-timeout posture, inventory-scoped memberships, and
  backup/restore recovery now exist in the supported single-host operating
  model. The current route surface also includes grouped bulk mutations,
  inventory transfer / duplication, and import / export preview/commit flows,
  while rollout validation and broader admin-surface policy are still
  follow-up work.

## Quick Start

This project requires Python 3.12. If you want an isolated environment, use a
virtualenv first:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e .
```

If you want to run the demo web API shell too, install the optional web extra:

```bash
pip install -e '.[web]'
```

The current `mtg-web-api` shell supports two runtime modes over the existing
inventory services:

- `local_demo` is the default local-first mode for UI and contract work
- `shared_service` uses safer startup defaults for a pre-migrated, single-host
  SQLite deployment with WAL and busy-timeout enabled through the shared
  connection layer

`shared_service` is a better fit for modest shared use. It now expects verified
upstream identity for the app route surface, and the recommended first-live
deployment shape is a same-origin reverse proxy over the current root-route API
surface.

In `local_demo`, the API ignores caller-supplied `X-Actor-Id` headers and
records mutating audit entries as coming from `local-demo`. For explicit
local/dev testing, set `MTG_API_TRUST_ACTOR_HEADERS=true` to trust
header-supplied actor IDs instead. `X-Request-Id` remains accepted for request
tracing.

In `shared_service`, every current app/API route except `/health` and public
share-link reads under `/shared/inventories/{share_token}` requires an
authenticated app user. The default verified identity header is
`X-Authenticated-User`, and you can override it with
`MTG_API_AUTHENTICATED_ACTOR_HEADER`.

Deck URL preview/commit flows also use a short-lived signed snapshot token.
Public inventory share links use the same signing-secret setting to make
reusable links recoverable without storing the full bearer token in the
database. `local_demo` ships with a built-in default signing secret for these
flows. `shared_service` requires an explicit
`MTG_API_SNAPSHOT_SIGNING_SECRET`; rotating it invalidates existing deck preview
tokens and public inventory share URLs.

`shared_service` also supports a normalized roles header,
`X-Authenticated-Roles` by default, with `editor` and `admin` as the current
recognized global app roles. If the verified user header is present and no
roles header is supplied, the caller is authenticated with no global roles.
`admin` implies `editor`.

Inventory access is now controlled by local inventory memberships:

- `viewer` can read a specific inventory
- `editor` can read and write a specific inventory
- `owner` can read and write a specific inventory
- global `admin` bypasses inventory membership checks

The current shared-service behavior is:

- `GET /inventories` returns only the inventories visible to the current user
- card search routes require a user who can read at least one inventory
- inventory item/audit reads require membership on that inventory
- inventory writes require `editor` or `owner` membership on that inventory
- `POST /inventories` lets any authenticated user create an owned inventory
- `POST /me/bootstrap` creates one personal default inventory named
  `Collection` for an authenticated user, grants `owner`, and returns the same
  inventory on repeated calls

For the first live cohort, the recommended deployment shape is:

- same-origin frontend and backend
- reverse proxy publishes `/api` and strips that prefix before forwarding
- reverse proxy injects verified `X-Authenticated-User`
- reverse proxy optionally injects normalized `X-Authenticated-Roles`
- backend binds loopback or a private interface behind the proxy

Run the local-demo API:

```bash
mtg-web-api --db "var/db/mtg_mvp.db"
```

Run the safer shared-service startup mode against a pre-migrated DB:

```bash
MTG_API_SNAPSHOT_SIGNING_SECRET="replace-with-a-long-random-secret" \
mtg-web-api --db "var/db/mtg_mvp.db" --runtime-mode shared_service
```

If you need to override startup migration behavior explicitly, use
`--auto-migrate` or `--no-auto-migrate`, or set `MTG_API_AUTO_MIGRATE`.

API import routes follow that startup schema posture. `POST /imports/csv`,
`POST /imports/decklist`, and `POST /imports/deck-url` require a current
database and do not auto-migrate during request handling. If the schema is
stale, migrate it intentionally first with `mtg-mvp-importer migrate-db` or
start the API with auto-migrate enabled.

`shared_service` also supports:

- `--proxy-headers` / `--no-proxy-headers`
- `--forwarded-allow-ips`
- `MTG_API_SNAPSHOT_SIGNING_SECRET` as a required shared-service environment
  variable for signed deck URL snapshot tokens

The current recommended deployment runbook lives in
[`docs/shared_service_deploy.md`](docs/shared_service_deploy.md).

Initialize a local database:

```bash
mtg-mvp-importer init-db --db "var/db/mtg_mvp.db"
```

Refresh from the official bulk sources:

```bash
mtg-mvp-importer sync-bulk \
  --db "var/db/mtg_mvp.db" \
  --cache-dir "var/bulk_cache/latest"
```

Recommended ongoing refresh cadence:

```bash
mtg-mvp-importer sync-scryfall --db "var/db/mtg_mvp.db" --cache-dir "var/bulk_cache/latest"
mtg-mvp-importer sync-identifiers --db "var/db/mtg_mvp.db" --cache-dir "var/bulk_cache/latest"
mtg-mvp-importer sync-prices --db "var/db/mtg_mvp.db" --cache-dir "var/bulk_cache/latest"
```

For most local or modest shared-service use, treat those commands as:

- `sync-prices`: daily
- `sync-scryfall`: weekly
- `sync-identifiers`: weekly or less often
- `sync-bulk`: catch-up/bootstrap command when you want one operator action to refresh everything

Search index maintenance and sync history:

```bash
mtg-mvp-importer check-search-index --db "var/db/mtg_mvp.db"
mtg-mvp-importer rebuild-search-index --db "var/db/mtg_mvp.db"
mtg-mvp-importer list-sync-runs --db "var/db/mtg_mvp.db"
mtg-mvp-importer show-sync-run --db "var/db/mtg_mvp.db" --run-id 42
```

Important upgrade note:

- migration `0008` adds the durable catalog-classification fields used by the
  default app-facing card-search scope
- existing databases can migrate in place, but legacy rows only get a
  best-effort backfill from older `type_line` data
- after upgrading an existing catalog, run a fresh Scryfall bulk import before
  relying on the narrowed default add-search scope for tokens, emblems,
  art-series rows, digital-only rows, and other auxiliary catalog objects

Or import from local bulk files you already downloaded:

```bash
mtg-mvp-importer import-all \
  --db "var/db/mtg_mvp.db" \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json
```

Create an inventory, search the catalog, and add a card:

```bash
mtg-personal-inventory create-inventory \
  --db "var/db/mtg_mvp.db" \
  --slug personal \
  --display-name "Personal Collection"

mtg-personal-inventory search-cards \
  --db "var/db/mtg_mvp.db" \
  --query "Lightning Bolt"

mtg-personal-inventory add-card \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --oracle-id YOUR_CARD_ORACLE_ID \
  --quantity 4 \
  --condition NM \
  --finish normal \
  --location "Red Binder" \
  --tags "burn deck,trade"
```

`add-card` now accepts `--oracle-id` as a first-class identifier as well as
`--scryfall-id`. Inventory rows still store the resolved printing, and if you
omit `--language-code` the owned row inherits the resolved printing language.

For shared-service rollout and ongoing membership management, the inventory CLI
now also provides:

```bash
mtg-personal-inventory grant-inventory-membership \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --actor-id alice@example.com \
  --role viewer

mtg-personal-inventory list-inventory-memberships \
  --db "var/db/mtg_mvp.db" \
  --inventory personal

mtg-personal-inventory revoke-inventory-membership \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --actor-id alice@example.com
```

For greenfield shared-service onboarding, the API can also create a personal
default inventory exactly once per user:

```bash
curl -X POST \
  -H "X-Authenticated-User: alice@example.com" \
  http://127.0.0.1:8000/me/bootstrap
```

That creates a `Collection` inventory for the actor if they do not already have
one and immediately unlocks card search under the current membership-gated
shared-service model.

Preview a CSV import with the bundled sample file:

```bash
mtg-personal-inventory import-csv \
  --db "var/db/mtg_mvp.db" \
  --csv "examples/sample_inventory_import.csv" \
  --inventory personal \
  --dry-run \
  --report-out "var/reports/import_preview.txt" \
  --report-out-json "var/reports/import_preview.json" \
  --report-out-csv "var/reports/import_preview.csv"
```

Generate a quick valuation view and a full report:

```bash
mtg-personal-inventory list-owned \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory inventory-report \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --report-out "var/reports/personal_report.txt" \
  --report-out-json "var/reports/personal_report.json" \
  --report-out-csv "var/reports/personal_report_rows.csv"
```

## Frontend Demo Bootstrap

For local frontend work, the backend-owned demo bootstrap now supports two
modes.

Small default demo:

```bash
cd frontend
npm install
npm run demo:bootstrap -- --force
```

This keeps the tiny built-in catalog and the curated richer demo inventory.

Full searchable catalog demo:

```bash
npm run demo:bootstrap -- \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json
```

That mode imports real Scryfall-backed `mtg_cards` rows, then resolves the same
curated demo inventory against real printings instead of the built-in demo
catalog. The curated rows now flow through the same `oracle_id` default
printing policy used by the app, so upstream catalog drift fails early with a
clear bootstrap error instead of a later finish-mismatch surprise. It is the
better fit when the frontend should search a realistic card catalog while still
keeping the owned demo rows intentionally curated.

If you also want real MTGJSON-backed price snapshots in that full-catalog demo
database:

```bash
npm run demo:bootstrap -- \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json
```

Without those MTGJSON files, full-catalog mode keeps the curated demo price
seed for the showcase owned rows only.

Recommended local API start from the frontend sandbox:

```bash
npm run backend:demo
```

The frontend demo launchers prefer the repo-local `.venv/bin/python` when it
exists, force `PYTHONPATH` to this checkout, and avoid the false
cross-checkout/schema-mismatch problems that can happen with a globally
installed `mtg-web-api` wrapper.

For the fuller maintenance surface, check `--help` on:

- `set-quantity`
- `set-finish`
- `set-location`
- `set-condition`
- `set-acquisition`
- `set-notes`
- `set-tags`
- `split-row`
- `merge-rows`
- `remove-card`
- `inventory-health`
- `price-gaps`
- `reconcile-prices`
- `export-csv`
- `valuation`

## Safety Snapshots

High-impact write commands create automatic safety snapshots only after
validation passes and immediately before they write. You can also manage
snapshots directly:

```bash
mtg-mvp-importer snapshot-db \
  --db "var/db/mtg_mvp.db" \
  --label "before_cleanup"

mtg-mvp-importer list-snapshots \
  --db "var/db/mtg_mvp.db"

mtg-mvp-importer restore-snapshot \
  --db "var/db/mtg_mvp.db" \
  --snapshot SNAPSHOT_NAME_FROM_LIST
```

## Shared-Service SQLite Runbook

For the current shared-service phase, the intended deployment shape is:

- one app process
- one SQLite database file
- one host
- local disk storage
- a pre-migrated database started with `--runtime-mode shared_service` and an
  explicit `MTG_API_SNAPSHOT_SIGNING_SECRET`

Operational expectations:

- the shared connection layer enables SQLite `WAL`, `busy_timeout`,
  `synchronous=NORMAL`, and `foreign_keys=ON`
- run the API behind an auth boundary that injects a verified user header such
  as `X-Authenticated-User`
- if you forward app roles, normalize them to global app roles `editor` and
  `admin` in a header such as `X-Authenticated-Roles`
- if no roles header is forwarded, the user is authenticated with no global
  roles but can still create and own their own inventories
- publish the API to browsers through a same-origin reverse proxy, not by
  exposing the backend directly
- validate snapshot backup and restore before live use
- keep the database on local storage, not a shared/network filesystem
- treat `sync-bulk`, `import-all`, and large import/update jobs as admin
  operations and avoid running them during active user editing windows
- grant inventory memberships intentionally before shared use; inventories with
  no memberships are effectively admin-only

Recommended rollout sequence:

1. Migrate the DB intentionally.
2. Start the API in `shared_service`.
3. If you are starting from a blank system, let first users create inventories
   through the app or `POST /inventories` so creators become `owner`. Use
   `POST /me/bootstrap` only when the default `Collection` name is acceptable,
   or use the CLI membership commands to assign owners on existing inventories.
4. Grant `viewer` / `editor` memberships to the first cohort.
5. Verify real user sessions against those memberships before launch.

A typical startup flow is:

```bash
mtg-mvp-importer migrate-db --db "var/db/mtg_mvp.db"
MTG_API_SNAPSHOT_SIGNING_SECRET="replace-with-a-long-random-secret" \
mtg-web-api --db "var/db/mtg_mvp.db" --runtime-mode shared_service
```

## Testing

With the virtualenv active, run the full local test suite:

```bash
./scripts/test_backend.sh
```

That wrapper forces this checkout's `src/` tree onto `PYTHONPATH` before
running `unittest`, which avoids accidentally importing a different editable
checkout in multi-repo environments.

## Repo Map

- `src/mtg_source_stack/`
  Active runtime package: API shell, CLI entrypoints, DB layer, importer, and
  inventory domain code.
- `docs/README.md`
  Entry point for the documentation set and recommended reading order.
- `docs/architecture.md`
  High-level orientation for package boundaries and public surfaces.
- `docs/backend_v1_contract.md`
  Current backend product rules and live schema scope.
- `docs/ingestion_flow.md`
  How Scryfall and MTGJSON bulk data become local runtime tables.
- `docs/api_v1_contract.md`
  JSON serialization, API error-shaping, and demo-shell runtime rules for the
  current web API layer.
- `docs/frontend_handoff.md`
  Frontend/backend ownership boundary, demo scope, and integration rules for a
  UI specialist.
- `docs/frontend_backend_requests/`
  Optional supporting specs and historical notes for frontend-requested
  backend/API work. GitHub issues and PRs are the only live tracker.
- `contracts/`
  OpenAPI snapshot and example JSON payloads for frontend integration.
- `scripts/`
  Small backend-owned utility scripts, including the frontend demo-data
  bootstrap path.
- `docs/source_map.md`
  Upstream source strategy and future integration notes.
- `examples/sample_inventory_import.csv`
  Small sample CSV for import walkthroughs.
- `examples/sample_queries.sql`
  Current MVP-schema SQL examples for ad hoc SQLite inspection.
- `notebooks/`
  Contributor walkthrough series.
- `frontend/`
  Reserved frontend sandbox for the demo UI.
- `tests/`
  Local integration and service-level test coverage.
- `var/`
  Recommended generated local state for databases, bulk cache, reports, and
  walkthrough output.

## Notebook Walkthroughs

- `notebooks/00_repo_architecture_walkthrough.ipynb`
  Repo map, package boundaries, and where the main workflows live.
- `notebooks/01_db_and_migrations_walkthrough.ipynb`
  Database initialization, migrations, schema readiness, and snapshots.
- `notebooks/02_importer_walkthrough.ipynb`
  Scryfall and MTGJSON ingest flow into the local SQLite catalog.
- `notebooks/03_inventory_domain_walkthrough.ipynb`
  Inventory creation, card search, row mutations, and CSV import behavior.
- `notebooks/04_reporting_and_api_contract_walkthrough.ipynb`
  Reporting, valuation, export flow, and API-facing serialization/error rules.

## Current Limitations

- The repo is intentionally local-first and CLI-driven.
- `mtg-web-api` now supports a safer `shared_service` runtime mode with
  verified-user audit attribution, inventory-scoped memberships, and a
  documented first-live reverse-proxy deployment shape. Admin-only surface
  policy and rollout validation still need follow-up before broader shared use.
- The demo API exposes a minimal `/health` payload focused on status and mode,
  not filesystem path details.
- The demo API ignores caller-supplied `X-Actor-Id` values by default and
  stamps writes as `local-demo` unless trusted-header mode is explicitly
  enabled.
- In `shared_service`, non-health routes require an authenticated app user
  except public share-link reads under `/shared/inventories/{share_token}`.
  Inventory reads and writes are scoped by local memberships. Authenticated
  users can create inventories they own; global roles are only for elevated app
  permissions such as admin bypass. The default verified identity header is
  `X-Authenticated-User`, and the default roles header is
  `X-Authenticated-Roles`.
- The recommended first-live deployment is same-origin and proxy-based. The
  backend is not yet intended to be exposed directly to browsers on a separate
  origin.
- The current shared-service SQLite posture is single-host only and depends on
  WAL, busy-timeout, and tested snapshot restore rather than a distributed DB
  story.
- Ordinary read commands do not do automatic live Scryfall fallback.
- The runtime model is the MVP schema, not the normalized future schema.
- Price imports currently keep USD retail and buylist snapshots only so
  valuation and health checks stay unambiguous.
- `reconcile-prices` is suggestion-only; it does not mutate inventory finishes.

## Next API Hardening Steps

Before treating the API shell as more than a local/demo surface, the next
planned hardening steps are:

- rollout rehearsal against the real proxy/header/membership setup
- clearer admin-only policy for maintenance surfaces
