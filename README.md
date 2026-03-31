# MTG Inventory Tool

A local-first Magic: The Gathering inventory workflow built around SQLite,
Scryfall, and MTGJSON.

Use it to:

- import MTG catalog and pricing data from Scryfall and MTGJSON
- create one or more personal inventories
- add owned printings with condition, finish, language, and location
- value the collection from imported daily USD price snapshots
- keep a per-edit audit trail for inventory mutations

If you're new to the repo, the best starting points are this README, the
walkthrough notebook in `notebooks/`, and the architecture notes in `docs/`.

For backend work, the canonical web-v1 contract is the current MVP runtime
schema in `src/mtg_source_stack/mtg_mvp_schema.sql` and `docs/schema_mvp.sql`.
`docs/schema_full.sql` is a future normalized target, not the live runtime
model.

The Python package lives under `src/mtg_source_stack/`. The recommended way to
use the repo is `pip install -e .` plus the
`mtg-mvp-importer` and `mtg-personal-inventory` commands.

## Project Layout

- Runtime package:
  - `src/mtg_source_stack/cli/`
  - `src/mtg_source_stack/db/`
  - `src/mtg_source_stack/importer/`
  - `src/mtg_source_stack/inventory/`
- Recommended generated local state:
  - `var/db/`
  - `var/bulk_cache/`
  - `var/reports/`
  - `var/walkthrough/`
- Docs and design notes:
  - `docs/api_v1_contract.md`
  - `docs/backend_v1_contract.md`
  - `docs/source_map.md`
  - `docs/ingestion_flow.md`
  - `docs/schema_full.sql`
  - `docs/schema_mvp.sql`
- Examples:
  - `examples/sample_queries.sql`
  - `examples/sample_inventory_import.csv`
- Notebook walkthrough:
  - `notebooks/mtg_source_stack_walkthrough.ipynb`
- Tests:
  - `tests/test_cli_smoke.py`
  - `tests/test_importer.py`
  - `tests/test_csv_import.py`
  - `tests/test_inventory_service.py`
  - `tests/fixtures/`

## Quick Start

Install the package in editable mode:

```bash
pip install -e .
```

Initialize a local database:

```bash
mtg-mvp-importer init-db --db "var/db/mtg_mvp.db"
```

Import local Scryfall and MTGJSON bulk files:

```bash
mtg-mvp-importer import-all \
  --db "var/db/mtg_mvp.db" \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json
```

Or refresh from the official bulk sources in one command:

```bash
mtg-mvp-importer sync-bulk \
  --db "var/db/mtg_mvp.db" \
  --cache-dir "var/bulk_cache/latest"
```

Create a manual safety snapshot, list snapshots, or restore one later:

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

Create a personal inventory:

```bash
mtg-personal-inventory create-inventory \
  --db "var/db/mtg_mvp.db" \
  --slug personal \
  --display-name "Personal Collection"
```

Search for a printing:

```bash
mtg-personal-inventory search-cards \
  --db "var/db/mtg_mvp.db" \
  --query "Lightning Bolt"
```

Catalog search can also be filtered by things like `--set-code`, `--rarity`,
`--finish`, and `--lang`.

Add a card you own:

```bash
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

If `add-card` hits an existing matching row, it increases quantity and unions
tags, but it will not silently overwrite notes or acquisition metadata.

Or import a batch from a CSV file:

```bash
mtg-personal-inventory import-csv \
  --db "var/db/mtg_mvp.db" \
  --csv "examples/sample_inventory_import.csv" \
  --inventory personal
```

To preview a CSV import and save a report without changing the DB:

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

If a CSV row omits finish information and the matched printing only exists in a
single catalog finish, the importer will no longer infer that finish for you.
Provide `finish` explicitly in the CSV when it matters, and use `--dry-run` to
preview validation results before importing.

Current pricing imports keep USD market snapshots only. Non-USD price rows are
ignored for now so valuation and health checks stay unambiguous.

TCGplayer collection-style exports are also supported, including `Collection Name`
and `Product ID` rows, with inventories auto-created from collection names when needed.
Seller Portal mass-update CSV exports are also supported too; those should be
imported with an explicit `--inventory` slug.

List your collection and get a valuation:

```bash
mtg-personal-inventory list-owned \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory set-quantity \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 2

mtg-personal-inventory set-finish \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --finish foil

mtg-personal-inventory set-location \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box"

mtg-personal-inventory set-location \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box" \
  --merge

# If the merge would combine rows with different acquisition values, choose
# which row's acquisition survives.
mtg-personal-inventory set-location \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box" \
  --merge \
  --keep-acquisition target

mtg-personal-inventory set-condition \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --condition LP

mtg-personal-inventory set-condition \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --condition LP \
  --merge

mtg-personal-inventory set-acquisition \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --price 2.50 \
  --currency USD

mtg-personal-inventory set-notes \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --notes "Needs fresh sleeve"

mtg-personal-inventory set-tags \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --tags "binder,trade"

mtg-personal-inventory split-row \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 1 \
  --location "Deck Box"

mtg-personal-inventory merge-rows \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --source-item-id 2 \
  --target-item-id 1 \
  --keep-acquisition source

mtg-personal-inventory remove-card \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --item-id 1

mtg-personal-inventory valuation \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory price-gaps \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory reconcile-prices \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory inventory-health \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

mtg-personal-inventory export-csv \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --output "var/reports/personal_export.csv"

mtg-personal-inventory inventory-report \
  --db "var/db/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --report-out "var/reports/personal_report.txt" \
  --report-out-json "var/reports/personal_report.json" \
  --report-out-csv "var/reports/personal_report_rows.csv"
```

`list-owned` and `valuation` also accept filters like `--set-code`, `--rarity`,
`--finish`, `--location`, and repeated `--tag` values for custom tags.

`reconcile-prices` is suggestion-only. It no longer updates inventory finish
values; review the suggestions and use `set-finish` manually if you want to
change a row.

High-impact commands now create automatic safety snapshots only after validation
passes and immediately before they write, including bulk imports, non-dry-run
CSV imports, `remove-card`,
`set-acquisition`, `split-row`, `merge-rows`, and collision merges from
`set-location --merge` / `set-condition --merge`.

## Testing

Run the smoke test suite:

```bash
python3 -m unittest discover -s tests -q
```

## Notes

- The project is intentionally local and script-driven.
- The bundled schema is designed to get a real personal inventory working
  quickly.
- The docs also include a fuller normalized schema if you want to grow this
  into a larger app later.
