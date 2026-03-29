# MTG Inventory Tool

This repo is now centered on a local-first Magic: The Gathering inventory
workflow built around the code in `MtG Source Stack/`.

The previous generic inventory prototype has been removed so the repo reflects a
single direction:

- import MTG catalog and pricing data from Scryfall and MTGJSON
- create one or more personal inventories
- add owned printings with condition, finish, language, and location
- value the collection from imported daily price snapshots

## Primary Code

The main runtime code lives in:

- `MtG Source Stack/mtg_source_stack/mvp_importer.py`
- `MtG Source Stack/mtg_source_stack/personal_inventory_cli.py`

Supporting design and schema files live alongside them:

- `MtG Source Stack/mtg_mvp_schema.sql`
- `MtG Source Stack/schema.sql`
- `MtG Source Stack/source_map.md`
- `MtG Source Stack/ingestion_flow.md`
- `MtG Source Stack/sample_queries.sql`

For convenience, the original top-level scripts in `MtG Source Stack/` are kept
as thin wrappers around the package entry points.

## Quick Start

Initialize a local database:

```bash
python3 "MtG Source Stack/mvp_importer.py" init-db --db "MtG Source Stack/mtg_mvp.db"
```

Import local Scryfall and MTGJSON bulk files:

```bash
python3 "MtG Source Stack/mvp_importer.py" import-all \
  --db "MtG Source Stack/mtg_mvp.db" \
  --scryfall-json /path/to/default-cards.json \
  --identifiers-json /path/to/AllIdentifiers.json \
  --prices-json /path/to/AllPricesToday.json
```

Or refresh from the official bulk sources in one command:

```bash
python3 "MtG Source Stack/mvp_importer.py" sync-bulk \
  --db "MtG Source Stack/mtg_mvp.db" \
  --cache-dir "MtG Source Stack/_bulk_cache/latest"
```

Create a manual safety snapshot, list snapshots, or restore one later:

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

Create a personal inventory:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" create-inventory \
  --db "MtG Source Stack/mtg_mvp.db" \
  --slug personal \
  --display-name "Personal Collection"
```

Search for a printing:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" search-cards \
  --db "MtG Source Stack/mtg_mvp.db" \
  --query "Lightning Bolt"
```

Catalog search can also be filtered by things like `--set-code`, `--rarity`,
`--finish`, and `--lang`.

Add a card you own:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" add-card \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --scryfall-id YOUR_PRINTING_ID \
  --quantity 4 \
  --condition NM \
  --finish normal \
  --location "Red Binder" \
  --tags "burn deck,trade"
```

Or import a batch from a CSV file:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" import-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --csv "MtG Source Stack/sample_inventory_import.csv" \
  --inventory personal
```

To preview a CSV import and save a report without changing the DB:

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

If a CSV row omits finish information and the matched printing only exists in a
single catalog finish, the importer will auto-correct that row and include the
change in the import summary report.

TCGplayer collection-style exports are also supported, including `Collection Name`
and `Product ID` rows, with inventories auto-created from collection names when needed.
Seller Portal mass-update CSV exports are also supported too; those should be
imported with an explicit `--inventory` slug.

List your collection and get a valuation:

```bash
python3 "MtG Source Stack/personal_inventory_cli.py" list-owned \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

python3 "MtG Source Stack/personal_inventory_cli.py" set-quantity \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 2

python3 "MtG Source Stack/personal_inventory_cli.py" set-finish \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --finish foil

python3 "MtG Source Stack/personal_inventory_cli.py" set-location \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box"

python3 "MtG Source Stack/personal_inventory_cli.py" set-location \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --location "Deck Box" \
  --merge

python3 "MtG Source Stack/personal_inventory_cli.py" set-condition \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --condition LP

python3 "MtG Source Stack/personal_inventory_cli.py" set-condition \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --condition LP \
  --merge

python3 "MtG Source Stack/personal_inventory_cli.py" set-acquisition \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --price 2.50 \
  --currency USD

python3 "MtG Source Stack/personal_inventory_cli.py" set-notes \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --notes "Needs fresh sleeve"

python3 "MtG Source Stack/personal_inventory_cli.py" set-tags \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --tags "binder,trade"

python3 "MtG Source Stack/personal_inventory_cli.py" split-row \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1 \
  --quantity 1 \
  --location "Deck Box"

python3 "MtG Source Stack/personal_inventory_cli.py" merge-rows \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --source-item-id 2 \
  --target-item-id 1

python3 "MtG Source Stack/personal_inventory_cli.py" remove-card \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --item-id 1

python3 "MtG Source Stack/personal_inventory_cli.py" valuation \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

python3 "MtG Source Stack/personal_inventory_cli.py" price-gaps \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

python3 "MtG Source Stack/personal_inventory_cli.py" reconcile-prices \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --apply

python3 "MtG Source Stack/personal_inventory_cli.py" inventory-health \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer

python3 "MtG Source Stack/personal_inventory_cli.py" export-csv \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --output "MtG Source Stack/personal_export.csv"

python3 "MtG Source Stack/personal_inventory_cli.py" inventory-report \
  --db "MtG Source Stack/mtg_mvp.db" \
  --inventory personal \
  --provider tcgplayer \
  --report-out "MtG Source Stack/personal_report.txt" \
  --report-out-json "MtG Source Stack/personal_report.json" \
  --report-out-csv "MtG Source Stack/personal_report_rows.csv"
```

`list-owned` and `valuation` also accept filters like `--set-code`, `--rarity`,
`--finish`, `--location`, and repeated `--tag` values for custom tags.

High-impact commands now create automatic safety snapshots before they write, including
bulk imports, non-dry-run CSV imports, `remove-card`, `reconcile-prices --apply`,
`set-acquisition`, `split-row`, `merge-rows`, and collision merges from
`set-location --merge` / `set-condition --merge`.

## Testing

Run the smoke test suite:

```bash
python3 -m unittest tests/test_mtg_source_stack.py
```

## Installable Commands

The repo now has installable console entry points:

```bash
pip install -e .
mtg-mvp-importer init-db --db "MtG Source Stack/mtg_mvp.db"
mtg-personal-inventory list-inventories --db "MtG Source Stack/mtg_mvp.db"
```

## Notes

- The current implementation is intentionally local and script-driven.
- The MVP schema is optimized for getting a real personal inventory working
  quickly.
- The fuller normalized schema is still available if you want to grow this into
  a larger app later.
