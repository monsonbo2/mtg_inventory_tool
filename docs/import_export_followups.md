# Import / Export Follow-Ups

This note captures the highest-value follow-up work that remains after the
current import/export backend slice:

- CSV import API
- decklist text import API
- deck URL import API
- profile-based CSV export API

Current deck URL providers:

- Archidekt
- AetherHub
- ManaBox
- Moxfield
- MTGGoldfish
- MTGTop8
- TappedOut

## Highest-Value Next Work

### Frontend UX

- Build paste-import UI on top of `POST /imports/decklist` with preview and
  commit flow.
- Build URL-import UI on top of `POST /imports/deck-url`, including clear
  provider-specific error messaging when a remote site blocks automated fetches.
- Add CSV import and export controls in the frontend, including profile
  selection for exports.

### More URL / Text Sources

- Add more deck URL providers where public payloads are stable enough:
  `Deckstats`, `Scryfall`, `TCGplayer`, `Untapped.gg`, and similar sources.
- Treat `EDHREC` as text or clipboard import first rather than URL-first,
  because its public value is stronger as a decklist source than as a hosted
  deck payload source.
- Consider a second fallback path for providers that frequently block backend
  fetches: user-pasted export text routed through `POST /imports/decklist`.

### Richer Import Semantics

- Parse richer pasted-text metadata when a source format actually exposes it:
  finish, language, condition, and possibly acquisition notes.
- Persist deck section semantics if the product needs more than additive
  inventory import. Today section data is returned in the import report only.
- If deck ownership becomes important, add an explicit deck model instead of
  overloading inventory rows with deck structure.

## Quality-of-Life Improvements

### Provider Hardening

- Add provider-specific telemetry so blocked fetches, missing decks, and parse
  drift can be distinguished quickly in logs.
- Add retries or narrower error mapping only where providers prove flaky in
  practice.
- Capture more real-world provider fixtures so parser regressions are caught
  before live users hit them.

### Import UX

- Surface ambiguity suggestions for name-only imports instead of returning only
  a hard validation error.
- Add preview summaries such as total cards, distinct cards, sections, and
  unresolved lines.
- Consider optional source tags such as `imported-from:moxfield` or
  `section:sideboard` if users want provenance carried into inventory rows.

### Export UX

- Add real website-specific CSV export profiles on top of the current
  profile-based export engine.
- Version profile names once external consumers depend on them, so future
  column changes do not silently break downstream workflows.
- Consider multi-profile or multi-inventory export workflows if the frontend
  needs bulk download behavior.

## Architectural Caution

The current backend is intentionally additive and inventory-first:

- imports add cards into an existing inventory
- imports are transactional and all-or-nothing
- HTTP import routes do not implicitly create inventories
- deck sections are not persisted as first-class data

That is the right posture for v1. If the product later needs true deck
management, deck syncing, replace semantics, or provider-backed refreshes, that
should be designed as a separate deck domain rather than layered onto the
current inventory import path by accident.
