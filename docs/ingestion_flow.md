# Ingestion Flow

This document describes the current runtime ingestion flow used by the web-v1
backend contract. For the canonical backend decision, see
`docs/backend_v1_contract.md`.

## Core Principle

Build the app around a local SQLite catalog.
Use bulk source files to refresh the local catalog, not live APIs on every
screen request.

## Current Runtime Tables

The current importer writes into:

- `mtg_cards`
- `price_snapshots`
- `inventories`
- `inventory_items`

The normalized tables described in `docs/schema_full.sql` are future-target
design notes, not the live ingestion model.

## Daily Bulk Sync

Current recommended order:

1. Ensure the local database exists and is initialized.
2. Download or locate Scryfall bulk `default-cards`.
3. Upsert printing-level card rows into `mtg_cards`.
4. Download or locate MTGJSON `AllIdentifiers`.
5. Update `mtg_cards` vendor-id fields and `mtgjson_uuid` when a row matches by
   `scryfallId`, or by existing `mtgjson_uuid` for older linked rows.
6. Download or locate MTGJSON `AllPricesToday`.
7. Resolve MTGJSON UUIDs through the local `mtg_cards.mtgjson_uuid` mapping.
8. Insert or update `price_snapshots` rows by provider, finish, price kind,
   currency, and snapshot date.

There is currently no `source_sync_runs` bookkeeping table in the live schema.

## Current Lookup Behavior

- Catalog search is local-only.
- The CLI and notebook workflows do not perform automatic live Scryfall fallback
  during ordinary search commands.
- `sync-bulk` can fetch fresh bulk files, but read paths query SQLite only.

## Price Refresh Strategy

Current runtime rules:

- store snapshots by provider and date
- compute current prices in application queries
- keep retail and buylist as separate price kinds
- keep one row per provider + finish + price kind + currency + day

Current constraint:

- imported market data is restricted to USD so downstream valuation and health
  queries stay unambiguous

## Matching Strategy

Current identifier matching order:

1. `scryfall_id`
2. existing `mtgjson_uuid`

Not implemented yet in the live importer:

- fallback matching by `oracle_id + set_code + collector_number + lang`
- vendor-specific fallback matching
- unresolved-import tracking tables

## Authority Rules

- Scryfall defines the local printing rows imported into `mtg_cards`.
- MTGJSON enriches those rows with vendor IDs and price snapshots.
- Imported price snapshots keep USD-only market data for now and normalize
  finish aliases like `nonfoil` into the inventory finish vocabulary.
- Inventory rows always point at a local `mtg_cards` printing record.

## Failure Strategy

If a bulk import fails:

- keep the last successful local catalog rows already in SQLite
- do not delete existing rows because one source payload failed
- surface the import error to the operator

If identifier matching fails:

- skip the unmatched identifier or price rows
- leave existing linked rows unchanged
- do not guess across multiple candidate printings

## Suggested Job Cadence

- Scryfall bulk catalog sync: daily
- MTGJSON identifiers sync: daily or weekly
- MTGJSON prices today sync: daily
- targeted live fetches: not part of the ordinary current runtime flow

## Mapping Summary

Scryfall object to local tables:

- printing-level fields -> `mtg_cards`

MTGJSON identifiers to local tables:

- `mtgjson_uuid` and vendor ID columns -> `mtg_cards`

MTGJSON prices to local tables:

- daily price snapshots -> `price_snapshots`

Inventory app actions to local tables:

- user-owned copies -> `inventory_items`
- per-edit mutation history -> `inventory_audit_log`

## Example End-To-End Flow

1. Operator runs Scryfall bulk import.
2. The importer upserts printings into `mtg_cards`.
3. Operator runs MTGJSON identifier import.
4. Matching rows in `mtg_cards` gain `mtgjson_uuid` and vendor identifiers.
5. Operator runs MTGJSON price import.
6. The importer resolves local `mtg_cards` rows by `mtgjson_uuid`.
7. Imported prices are written into `price_snapshots`.
8. User searches cards from the local catalog.
9. User creates or increments an `inventory_items` row for the owned printing.
10. Valuation and health queries join `inventory_items` to the latest matching
    `price_snapshots` rows.
