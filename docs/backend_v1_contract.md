# Backend V1 Contract

This document defines the canonical backend model for the first web-backed
version of this project.

## Decision

Web-v1 is built on the current MVP runtime schema, not the fully normalized
future design.

Canonical schema files:

- Runtime schema: `src/mtg_source_stack/mtg_mvp_schema.sql`
- Docs mirror: `docs/schema_mvp.sql`

Future-target design only:

- `docs/schema_full.sql`

## Current Runtime Tables

The live backend contract consists of four primary tables:

- `mtg_cards`
  Stores printing-level catalog rows imported from Scryfall, plus selected
  MTGJSON/vendor identifiers on the same row.
- `price_snapshots`
  Stores provider/finish/price-kind/currency/date snapshots for a printing.
- `inventories`
  Stores named inventory containers.
- `inventory_items`
  Stores owned printings keyed by inventory + printing + condition + finish +
  language + location.

## Current Product Rules

- Inventory ownership is modeled as current positions, not as a movement
  ledger.
- Quantity edits mutate `inventory_items` in place.
- Operator safety comes from explicit commands plus whole-database snapshots.
- Pricing imports currently keep USD snapshots only.
- MTGJSON identifier matching currently relies on `scryfallId` first, then an
  existing `mtgjson_uuid` when present.
- Catalog search and reporting operate entirely on the local SQLite database.

## Intentional V1 Limitations

The following are not part of the web-v1 backend contract yet:

- `source_sync_runs`
- `oracle_cards`
- `card_printings`
- `printing_external_ids`
- `inventory_positions`
- `inventory_movements`
- per-edit audit history
- automatic live Scryfall fallback during ordinary search requests

Those concepts remain valid future directions, but they are not the current
runtime model and should not be treated as implemented backend behavior.

## What This Means For New Work

- Backend and API work should target the MVP schema first.
- Docs should describe the MVP schema as the live system.
- The normalized schema is a future migration target, not the current source of
  truth.
- Migration work should evolve from the MVP schema forward, rather than assume
  the normalized schema already exists.
