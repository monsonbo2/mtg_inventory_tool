# Source Map

## Recommended Sources

### Scryfall

Use Scryfall for:

- autocomplete and search
- exact card lookups
- oracle text
- legality
- image URIs
- set and printing metadata
- quick card-level price display

Why it belongs in the stack:

- strongest public MTG lookup API
- excellent print-level IDs
- strong image and search support
- bulk exports available for local sync

Operational notes:

- cache aggressively
- prefer bulk downloads for full refreshes
- use live API for targeted refreshes and cache misses
- do not hammer it for repeated full-catalog rebuilds

### MTGJSON

Use MTGJSON for:

- nightly bulk enrichment
- cross-vendor identifiers
- daily pricing snapshots
- 90-day pricing history

Why it belongs in the stack:

- it bridges Scryfall, TCGplayer, Card Kingdom, Cardmarket, and more
- it gives you a cleaner path to future marketplace adapters
- it is better than Scryfall for price history and vendor ID mapping

Operational notes:

- treat it as a bulk sync source rather than a user-facing search API
- use `AllIdentifiers` and `AllPricesToday` first
- add `AllPrices` only when you want charting and history

### TCGplayer

Use only if you need:

- authenticated seller inventory sync
- listing management
- marketplace-specific pricing behavior

Do not depend on it for:

- your primary public card catalog
- your only source of card metadata

### Mana Pool

Use only if you need:

- authenticated marketplace integration
- seller inventory and order workflows

Do not depend on it for:

- your canonical card database
- broad public MTG search and metadata

### Cardmarket

Use only if you need:

- EU-focused seller operations
- authenticated stock export and marketplace sync

Do not depend on it for:

- your first-pass app catalog
- your main image or rules-text source

### Card Kingdom

Recommendation:

- do not make Card Kingdom a direct API dependency up front
- use Card Kingdom IDs and prices indirectly through MTGJSON

Why:

- no strong public official developer surface was identified in this review
- MTGJSON already covers the pricing and identifier use cases you care about

## Field Ownership

Use `Scryfall` as the source of truth for:

- `oracle_id`
- `scryfall_id`
- name
- mana cost
- type line
- oracle text
- color identity
- collector number
- image URIs
- purchase URIs
- legality payloads
- set metadata that ships in Scryfall objects

Use `MTGJSON` as the source of truth for:

- `mtgjson_uuid`
- `tcgplayerProductId`
- `cardKingdomId`
- `mcmId`
- `cardsphereId`
- other external identifiers
- daily price snapshots
- price history

Use your own app as the source of truth for:

- owned quantity
- condition
- finish
- language actually owned
- location
- acquisition price
- notes
- trade and sale intent

## Conflict Policy

- If Scryfall and MTGJSON disagree on text or print metadata, prefer Scryfall.
- If Scryfall and MTGJSON disagree on vendor IDs, keep both raw values in sync
  logs and prefer the newest MTGJSON identifier mapping after manual review.
- If prices disagree, do not overwrite one provider with another.
  Store each provider as its own snapshot row.

## Minimal MVP Source Stack

- `Scryfall bulk + live API`
- `MTGJSON AllIdentifiers`
- `MTGJSON AllPricesToday`

This is enough to support:

- local search
- print-level inventory
- daily valuation
- future marketplace expansion
