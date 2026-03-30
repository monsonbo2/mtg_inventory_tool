# Ingestion Flow

## Core Principle

Build the app around a local SQLite catalog.
Use external APIs to refresh the local catalog, not to power every screen in
real time.

## Daily Bulk Sync

Recommended order:

1. Start a `source_sync_runs` row for `scryfall_bulk_default_cards`.
2. Download Scryfall bulk data and parse card objects.
3. Upsert `mtg_sets`.
4. Upsert `oracle_cards` keyed by `oracle_id`.
5. Upsert `card_printings` keyed by `scryfall_id`.
6. Replace `card_faces` rows for each touched printing.
7. Mark the sync run complete.
8. Start a `source_sync_runs` row for `mtgjson_all_identifiers`.
9. Download MTGJSON `AllIdentifiers`.
10. Upsert `printing_external_ids` by matching `scryfallId` or
    `scryfallOracleId` plus set and collector number when needed.
11. Mark the sync run complete.
12. Start a `source_sync_runs` row for `mtgjson_all_prices_today`.
13. Download MTGJSON `AllPricesToday`.
14. Resolve MTGJSON UUIDs to local printings.
15. Insert `price_snapshots` for each provider, finish, price kind, currency,
    and date.
16. Mark the sync run complete.

## Live Lookup Fallback

Use live Scryfall requests only when:

- a search result is not in the local cache yet
- a user opens a printing missing images or details
- you need a targeted refresh for a single card

Live flow:

1. Search local `card_printings` and `oracle_cards`.
2. If enough results exist locally, return them.
3. If not, query Scryfall live.
4. Upsert the returned printing and oracle card immediately.
5. Return the fresh local row to the caller.

## Price Refresh Strategy

Recommended default:

- `Scryfall` for light user-facing price display
- `MTGJSON AllPricesToday` for daily valuation
- `MTGJSON AllPrices` later for historical charting

Do not:

- overwrite yesterday's prices in place
- collapse all providers into one number
- treat buylist and retail as the same metric

Do:

- store snapshots by provider and date
- compute the current displayed number in application queries
- keep one row per provider + finish + price kind + currency + day

## Matching Strategy

Preferred key order when joining inbound data:

1. `scryfall_id`
2. `mtgjson_uuid`
3. `oracle_id + set_code + collector_number + lang`
4. vendor-specific identifier

## Suggested Authority Rules

- Scryfall controls card identity and printing identity.
- MTGJSON enriches printings with vendor IDs and prices.
- Inventory rows point to a local printing record, never directly to a remote
  source payload.

## Failure Strategy

If one sync source fails:

- keep the last successful local catalog
- record the failed `source_sync_runs` row
- do not delete existing rows because a source was temporarily unavailable

If identifier matching fails:

- leave the existing printing in place
- record the unresolved source payload in a dead-letter log or a manual review
  table later
- never guess across multiple candidate printings

## Suggested Job Cadence

- Scryfall bulk catalog sync: daily
- MTGJSON identifiers sync: daily or weekly
- MTGJSON prices today sync: daily
- Scryfall live lookups: on demand only
- seller adapters: event-driven or scheduled later

## Mapping Summary

Scryfall object to local tables:

- set data -> `mtg_sets`
- oracle-level fields -> `oracle_cards`
- printing-level fields -> `card_printings`
- multi-face payloads -> `card_faces`

MTGJSON identifiers to local tables:

- vendor IDs -> `printing_external_ids`

MTGJSON prices to local tables:

- daily and historical prices -> `price_snapshots`

Inventory app actions to local tables:

- user-owned copies -> `inventory_positions`
- quantity changes -> `inventory_movements`

## Example End-To-End Flow

1. User searches for `Lightning Bolt`.
2. App checks local search tables.
3. If local rows exist, return them immediately.
4. If not, query Scryfall and upsert the matching printings.
5. User selects the exact printing.
6. App creates or increments an `inventory_positions` row for that printing,
   condition, finish, and location.
7. App records the quantity change in `inventory_movements`.
8. Daily price sync updates `price_snapshots`.
9. Valuation screens join inventory positions to the latest price snapshot.
