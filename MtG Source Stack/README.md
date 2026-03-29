# MtG Source Stack

This folder is intentionally separate from the current draft app in this repo.
It captures a recommended source stack, a normalized SQLite schema, and an
ingestion plan for a Magic: The Gathering inventory tool as of 2026-03-27.

Nothing in `src/` was changed as part of this work.

## Recommended Stack

- `Scryfall`
  - Use for live search, card detail lookup, images, oracle text, legality, and
    print-level card metadata.
  - Best source for user-facing search and per-card refreshes.
- `MTGJSON`
  - Use for nightly bulk sync, cross-system IDs, and price snapshots/history.
  - Best source for local database enrichment and vendor ID mapping.
- `Optional seller adapters`
  - Add later only if you need authenticated marketplace operations.
  - Good candidates are `TCGplayer`, `Mana Pool`, and `Cardmarket`.

## Source Ownership Rules

- `Scryfall` is the primary source of truth for:
  - oracle identity
  - print identity
  - images
  - text and legality
  - quick displayed prices
- `MTGJSON` is the primary source of truth for:
  - cross-vendor identifiers
  - bulk daily prices
  - 90-day price history
- `Seller APIs` are optional overlays for:
  - listing sync
  - seller inventory sync
  - orders
  - marketplace-specific pricing

## Files In This Folder

- `schema.sql`
  - Proposed normalized SQLite schema for sets, oracle cards, printings, prices,
    inventory positions, and sync runs.
- `mtg_mvp_schema.sql`
  - Smaller MTG-specific schema for a first working build before you need the
    full normalization in `schema.sql`.
- `mvp_importer.py`
  - Thin wrapper for the packaged importer entry point.
- `personal_inventory_cli.py`
  - Thin wrapper for the packaged personal inventory CLI entry point.
- `mtg_source_stack/`
  - Installable Python package containing the real importer and personal
    inventory CLI logic.
- `source_map.md`
  - Why each source is in the stack, what it owns, and what not to depend on.
- `ingestion_flow.md`
  - Nightly bulk sync flow, live lookup fallback flow, and conflict policy.
- `sample_queries.sql`
  - Example queries for valuation, vendor lookups, and stale data checks.
- `sample_inventory_import.csv`
  - Example CSV template for bulk personal inventory import.
- `mtg_source_stack_walkthrough.ipynb`
  - Notebook walkthrough of the importer, local catalog, personal inventory
    flow, and valuation flow using tiny sample payloads.

## Design Summary

- Keep both a rules-level identifier and a printing-level identifier.
  - Rules-level: `oracle_id`
  - Printing-level: `scryfall_id`
- Keep vendor IDs in a separate table instead of hard-coding columns for every
  marketplace and future data source.
- Store prices as dated snapshots so you can support:
  - current valuation
  - historical charts
  - multiple providers
  - retail vs buylist
- Keep inventory positions separate from card metadata so you can:
  - aggregate duplicates
  - track condition and finish
  - add movement history later without reshaping the card catalog

## Practical Build Order

1. Create the catalog tables from `schema.sql`.
2. Load Scryfall bulk data into `mtg_sets`, `oracle_cards`, `card_printings`,
   and `card_faces`.
3. Load MTGJSON `AllIdentifiers` into `printing_external_ids`.
4. Load MTGJSON `AllPricesToday` into `price_snapshots`.
5. Wire app search to local tables first, then use live Scryfall lookup as a
   cache-miss fallback.
6. Add seller adapters only when marketplace sync becomes a real requirement.

## MVP Shortcut

If you want to build faster before adopting the full schema, start with
`mtg_mvp_schema.sql`.

It keeps:

- a single printing table
- a compact price snapshot table
- a direct inventory table

It drops:

- sync run tracking
- separate oracle and face tables
- movement history
- extra normalization around provider IDs

## Importer Usage

The importer is intentionally isolated from the current app codebase.

The packaged module behind the wrapper lives at:

- `MtG Source Stack/mtg_source_stack/mvp_importer.py`

Initialize a fresh MVP database:

```bash
python3 "MtG Source Stack/mvp_importer.py" init-db --db "MtG Source Stack/mtg_mvp.db"
```

Import Scryfall bulk card data from a local JSON file:

```bash
python3 "MtG Source Stack/mvp_importer.py" import-scryfall \
  --db "MtG Source Stack/mtg_mvp.db" \
  --json /path/to/default-cards.json
```

Import MTGJSON identifier mappings:

```bash
python3 "MtG Source Stack/mvp_importer.py" import-identifiers \
  --db "MtG Source Stack/mtg_mvp.db" \
  --json /path/to/AllIdentifiers.json
```

Import MTGJSON daily prices:

```bash
python3 "MtG Source Stack/mvp_importer.py" import-prices \
  --db "MtG Source Stack/mtg_mvp.db" \
  --json /path/to/AllPricesToday.json
```

Run the full local import sequence:

```bash
python3 "MtG Source Stack/mvp_importer.py" import-all \
  --db "MtG Source Stack/mtg_mvp.db" \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json
```

Or run the one-command refresh flow, which downloads the latest official bulk
files into a cache directory and then imports them:

```bash
python3 "MtG Source Stack/mvp_importer.py" sync-bulk \
  --db "MtG Source Stack/mtg_mvp.db" \
  --cache-dir "MtG Source Stack/_bulk_cache/latest"
```

Create a manual safety snapshot, review saved snapshots, or restore one:

```bash
python3 "MtG Source Stack/mvp_importer.py" snapshot-db \
  --db "MtG Source Stack/mtg_mvp.db" \
  --label "before_cleanup"

python3 "MtG Source Stack/mvp_importer.py" list-snapshots \
  --db "MtG Source Stack/mtg_mvp.db"

python3 "MtG Source Stack/mvp_importer.py" restore-snapshot \
  --db "MtG Source Stack/mtg_mvp.db" \
  --snapshot SNAPSHOT_NAME_FROM_LIST
```

## Importer Notes

- The importer accepts `.json` and `.json.gz` files.
- It is written with the Python standard library only.
- It is a starter importer, not yet a production streaming pipeline.
- The MVP importer collapses some provider-specific ID variants into one column.
  The full schema is better when you need exact per-finish vendor ID storage.
- `sync-bulk` downloads the latest Scryfall `default_cards`, MTGJSON `AllIdentifiers`,
  and MTGJSON `AllPricesToday`, then runs the same import steps in sequence.
- `sync-bulk` stores downloaded files in a cache directory so you can inspect or reuse them later.
- The importer now creates automatic safety snapshots before `import-scryfall`,
  `import-identifiers`, `import-prices`, `import-all`, and `sync-bulk`.
- Snapshots are stored next to the database under `_snapshots/<db-stem>/` by default.
- `restore-snapshot` creates one more pre-restore snapshot of the current DB unless
  you pass `--no-pre-restore-snapshot`.

## Personal Inventory CLI

Once the catalog is imported, you can use the personal inventory CLI to manage a
real collection in the same MVP database.

The packaged module behind the wrapper lives at:

- `MtG Source Stack/mtg_source_stack/personal_inventory_cli.py`

Create an inventory:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" create-inventory \
  --db "MtG Source Stack/mtg_mvp.db" \
  --slug personal \
  --display-name "Personal Collection" \
  --description "Binders, boxes, and decks"
```

List your inventories:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" list-inventories \
  --db "MtG Source Stack/mtg_mvp.db"
```

Search the imported catalog:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" search-cards \
  --db "MtG Source Stack/mtg_mvp.db" \
  --query "Lightning Bolt"
```

You can also narrow the catalog search by set, rarity, finish, or language:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" search-cards \
  --db "MtG Source Stack/mtg_mvp.db" \
  --query "Lightning" \
  --set-code lea \
  --rarity common \
  --finish normal \
  --lang en
```

Add a card by exact Scryfall printing id:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" add-card \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --scryfall-id 77c6fa74-5543-42ac-9ead-0e890b188e99 \
  --quantity 4 \
  --condition NM \
  --finish normal \
  --location "Red Binder" \
  --tags "burn deck,trade"
```

Or add a card by exact name when the printing is unambiguous:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" add-card \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --name "Sol Ring" \
  --set-code clb \
  --collector-number 860 \
  --quantity 1 \
  --condition LP \
  --finish foil \
  --location "Commander Deck Box" \
  --tags "commander staple"
```

Import a batch of rows from a CSV file:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" import-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --csv "MtG Source Stack/sample_inventory_import.csv" \
  --inventory personal
```

Preview a CSV import without changing the database, and save the report:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" import-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --csv "MtG Source Stack/sample_inventory_import.csv" \
  --inventory personal \
  --dry-run \
  --report-out "MtG Source Stack/import_preview.txt" \
  --report-out-json "MtG Source Stack/import_preview.json" \
  --report-out-csv "MtG Source Stack/import_preview.csv"
```

When a CSV row does not include finish information and the matched printing has
exactly one catalog finish, the importer now auto-corrects the owned finish and
reports that change in the import summary. This is especially useful for
foil-only or etched-only printings in Archidekt-style exports.

TCGplayer collection-style CSV exports are also supported. If the file includes
`Collection Name`, the importer will derive an inventory slug and create that
inventory automatically during import:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" import-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --csv /path/to/tcgplayer_collection_export.csv
```

TCGplayer Seller Portal mass-update CSV exports are also supported. For that
format, pass an inventory slug because the seller export does not include a
collection name:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" import-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --csv /path/to/tcgplayer_seller_export.csv \
  --inventory seller-live
```

List owned cards with latest retail prices from a provider:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" list-owned \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer
```

You can filter owned rows by set, rarity, finish, location, and custom tags:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" list-owned \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --set-code lea \
  --rarity common \
  --finish normal \
  --tag "burn deck"
```

Set the quantity for an existing row using its `item_id` from `list-owned`:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-quantity \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 2
```

Set the finish for an existing row when you need to correct the owned finish:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-finish \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --finish foil
```

Set or clear the storage location for an existing row:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-location \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box"
```

Add `--merge` if changing the location would collide with an existing row and you want the tool to combine quantities, tags, and notes instead of failing:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-location \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box" \
  --merge
```

Set the condition code for an existing row:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-condition \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --condition LP
```

`set-condition` also supports `--merge` when the new condition would collapse into an existing row.

Set or clear acquisition price metadata for an existing row:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-acquisition \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --price 2.50 \
  --currency USD
```

Set or clear notes for an existing row:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-notes \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --notes "Needs fresh sleeve"
```

Replace the custom tags for an existing row:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-tags \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --tags "burn deck,foil project"
```

Or clear the tags entirely:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" set-tags \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --clear
```

Split a row when part of the quantity needs to move into a different bucket:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" split-row \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 1 \
  --location "Deck Box"
```

Merge two rows for the same printing when you want to explicitly collapse them:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" merge-rows \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --source-item-id 2 \
  --target-item-id 1
```

Remove an inventory row entirely:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" remove-card \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1
```

Run an inventory health report to spot missing metadata, stale prices, and likely duplicates:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" inventory-health \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --stale-days 30
```

Export the current inventory rows to CSV:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" export-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --output "MtG Source Stack/personal_export.csv"
```

Generate a reusable inventory report, with optional text, JSON, and CSV outputs:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" inventory-report \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --report-out "MtG Source Stack/personal_report.txt" \
  --report-out-json "MtG Source Stack/personal_report.json" \
  --report-out-csv "MtG Source Stack/personal_report_rows.csv"
```

Get a valuation summary:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" valuation \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer
```

If some imported rows are still unpriced, inspect the gaps and apply safe
finish updates when exactly one priced finish exists:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" price-gaps \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

python3 "MtG Source Stack/personal_inventory_cli.py" reconcile-prices \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --apply
```

The same filters also work on `valuation`, so you can value only a subset such as
cards with a given tag or cards from one set.

## Practical Workflow

1. Initialize and import the MVP database with `mvp_importer.py`.
2. Create one inventory, usually `personal`.
3. Use `search-cards` to find the exact printing you own.
4. Use `add-card` for one-off entries or `import-csv` for a spreadsheet-style batch import.
5. Use `list-owned` to review the current rows, tags, and each row's `item_id`.
6. Use `set-quantity`, `set-finish`, `set-location`, `set-condition`, `set-acquisition`, `set-notes`, `set-tags`, `split-row`, `merge-rows`, or `remove-card` when your collection changes. `set-location` and `set-condition` fail safely on collisions unless you opt into `--merge`.
7. Use `price-gaps` and `reconcile-prices --apply` when imported rows are missing prices because the owned finish does not match the priced finish.
8. Use `inventory-health` to catch missing location/tag data, stale prices, merge notes, and duplicate-like row groups.
9. Use `export-csv` when you want a spreadsheet-friendly snapshot of the current filtered rows.
10. Use `inventory-report` when you want a reusable summary with valuation, acquisition totals, top holdings, and health counts.
11. Use `valuation` to review the collection's current estimated value.

## CLI Notes

- `add-card` merges into an existing row when the same inventory, printing,
  condition, finish, language, and location already exist.
  Tags from repeated adds are merged into that row.
- `import-csv` uses the same merge behavior as `add-card`, but wraps the whole file
  in one transaction so a bad row does not leave you with a partial import.
- `import-csv` accepts either `scryfall_id` or `name` for card resolution.
  Helpful aliases like `set`, `number`, `qty`, `cond`, and `tag` are also supported.
- `import-csv --dry-run` exercises the full import logic and prints the same
  report you would get from a real import, but rolls back the transaction before exit.
- `import-csv --report-out <path>` saves the human-readable import report to disk.
- `import-csv --report-out-json <path>` saves the full structured import result as JSON.
- `import-csv --report-out-csv <path>` saves a flattened one-row-per-imported-card CSV report, including finish adjustments.
- `import-csv` auto-corrects obvious finish defaults when a matched printing has
  exactly one catalog finish and the CSV row did not specify one.
  The import output includes a finish-adjustment report.
- Non-dry-run `import-csv` runs create an automatic safety snapshot first.
- TCGplayer collection-style exports are supported through aliases such as
  `Collection Name`, `Product ID`, `Condition`, `Language`, `Variant`, and `Quantity`.
  `Product ID` maps to `tcgplayer_product_id`, `Collection Name` becomes an
  inventory, and `Variant` is used to infer finish.
- TCGplayer Seller Portal mass-update exports are supported through headings such as
  `TCGplayer ID`, `Product Name`, `Condition`, `Total Quantity`, and `Add to Quantity`.
  The importer uses `Total Quantity + Add to Quantity` as the resulting quantity and
  ignores seller listing prices like `TCG Marketplace Price`.
- `search-cards` supports `--set-code`, `--rarity`, `--finish`, and `--lang`.
- `list-owned` and `valuation` support filters like `--query`, `--set-code`,
  `--rarity`, `--finish`, `--condition`, `--language-code`, `--location`, and
  repeated `--tag` values.
- If the CSV does not include an `inventory` column, pass `--inventory` to supply
  a default inventory slug for every row.
- Tags are stored on inventory rows, not the global card catalog, so the same card
  can carry different tags in different inventories or locations.
- `set-quantity`, `set-finish`, `set-location`, `set-condition`, `set-acquisition`, `set-notes`, `set-tags`, `split-row`, and `remove-card` work on a specific inventory row by `item_id`.
- `set-location --merge` and `set-condition --merge` preserve the existing target row, sum quantities, union tags, and carry source notes forward instead of silently failing on a collision.
  Use `list-owned` first to find the row you want to edit.
- `merge-rows` explicitly collapses one row into another for the same printing while keeping the target row's bucket fields.
- `split-row` moves part of a row's quantity into a new or existing target bucket and is useful when one copy changes location, condition, finish, or language.
- `set-location --merge`, `set-condition --merge`, `set-acquisition`, `split-row`, `merge-rows`, `remove-card`, and `reconcile-prices --apply`
  create automatic safety snapshots before they write.
- Inventory finishes use `normal`, `foil`, or `etched`.
  If you pass `nonfoil`, the CLI maps it to `normal`.
- `price-gaps` shows rows whose current finish has no retail price for the selected provider.
- `reconcile-prices --apply` only updates rows when there is exactly one priced finish available, which makes it a safe post-import cleanup step.
- `inventory-health` summarizes missing price matches, empty locations, empty tags,
  rows carrying merged acquisition notes, stale prices, and duplicate-like groups.
- `export-csv` writes filtered inventory rows with item ids, IDs, acquisition fields,
  current unit price, and estimated value.
- `inventory-report` combines summary counts, valuation totals, tracked acquisition totals,
  top-valued holdings, and health counts into one printable report.
- Custom tags are normalized to lowercase and stored as a unique list.

## CSV Columns

The importer is intentionally flexible. A practical CSV usually includes:

- `inventory` or `--inventory`
- `inventory_name` or `Collection Name`
- `scryfall_id` or `name`
- `tcgplayer_product_id` or `Product ID`
- `TCGplayer ID`
- `set_code` or `set`
- `collector_number` or `number`
- `quantity` or `qty`
- `total_quantity`
- `add_to_quantity`
- `condition` or `cond`
- `variant`
- `finish`
- `language_code`
- `location`
- `tags`
- `acquisition_price`
- `acquisition_currency`
- `notes`

You can start from [sample_inventory_import.csv](/home/boydm9/inventory_tool2/MtG%20Source%20Stack/sample_inventory_import.csv) and edit it to match your collection.
- `search-cards` shows printings from your imported local catalog only.
  It does not call Scryfall live.
- The package is installable through the repo root `pyproject.toml`, with
  console scripts `mtg-mvp-importer` and `mtg-personal-inventory`.

## Notebook Walkthrough

If you want a guided tour of the current system, open:

- `MtG Source Stack/mtg_source_stack_walkthrough.ipynb`

The notebook:

- creates a scratch database
- writes tiny sample Scryfall and MTGJSON payloads
- imports them into the MVP schema
- creates a personal inventory
- adds example cards
- shows valuation output from both Python helpers and the CLI wrapper
