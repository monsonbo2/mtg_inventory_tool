# MTG Inventory Tool

A local-first Magic: The Gathering inventory workflow built around SQLite,
Scryfall, and MTGJSON.

Use it to:

- import a local MTG catalog and daily pricing snapshots
- create and maintain one or more personal inventories
- track condition, finish, language, location, tags, notes, and acquisition data
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

If you're planning frontend work, start with `docs/frontend_handoff.md` and
`contracts/openapi.json`.

## Current Runtime Shape

- The active runtime package lives in `src/mtg_source_stack/`.
- The current entrypoints are `mtg-mvp-importer`, `mtg-personal-inventory`, and
  the optional demo web shell `mtg-web-api`.
- The demo FastAPI layer lives in `src/mtg_source_stack/api/` and is currently
  intended for local/demo use rather than shared deployment.
- The runtime starts from `src/mtg_source_stack/mtg_mvp_schema.sql` and then
  applies the tracked migrations in `src/mtg_source_stack/db/migrations/`.
- `docs/schema_full.sql` is a future normalized design, not the live runtime
  model.
- Ordinary search, valuation, and reporting commands read from local SQLite
  only.
- `sync-bulk` can fetch fresh upstream bulk files, but normal read paths do not
  call live APIs.
- Pricing imports currently keep USD retail and buylist snapshots only.
- The current API shell intentionally keeps request handling simple and
  SQLite-backed; shared-deployment concurrency hardening is deferred to a later
  pass.

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
pip install -e .[web]
```

The current `mtg-web-api` shell is a local-demo layer over the existing
inventory services. It is useful for local UI and contract work, but it is not
yet positioned as a shared or production-ready deployment target.

By default, the API ignores caller-supplied `X-Actor-Id` headers and records
mutating audit entries as coming from `local-demo`. For explicit local/dev
testing, set `MTG_API_TRUST_ACTOR_HEADERS=true` to trust header-supplied actor
IDs instead. `X-Request-Id` remains accepted for request tracing.

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
  --scryfall-id YOUR_PRINTING_ID \
  --quantity 4 \
  --condition NM \
  --finish normal \
  --location "Red Binder" \
  --tags "burn deck,trade"
```

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

## Testing

With the virtualenv active, run the full local test suite:

```bash
python -m unittest discover -s tests -q
```

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
- `mtg-web-api` is currently a local/demo HTTP shell, not a concurrency-hardened
  shared service.
- The demo API exposes a minimal `/health` payload focused on status and mode,
  not filesystem path details.
- The demo API ignores caller-supplied `X-Actor-Id` values by default and
  stamps writes as `local-demo` unless trusted-header mode is explicitly
  enabled.
- The API now logs startup mode and unexpected failures, but it is still a
  local/demo shell rather than a shared-service deployment target.
- Ordinary read commands do not do automatic live Scryfall fallback.
- The runtime model is the MVP schema, not the normalized future schema.
- Price imports currently keep USD retail and buylist snapshots only so
  valuation and health checks stay unambiguous.
- `reconcile-prices` is suggestion-only; it does not mutate inventory finishes.

## Next API Hardening Steps

Before treating the API shell as more than a local/demo surface, the next
planned hardening steps are:

- execution-boundary and concurrency hardening for shared deployment
