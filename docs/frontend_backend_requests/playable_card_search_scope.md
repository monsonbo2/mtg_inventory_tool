# Frontend Backend Request: Playable Card Search Scope

Status: Proposed
Owner: Unassigned
GitHub issue: [#22](https://github.com/monsonbo2/mtg_inventory_tool/issues/22)
Implementation PR: Not linked yet
Last updated: 2026-04-02

## Frontend Backend Request

Feature / screen:

Card search and add flow

Current blocker:

The current search endpoints operate over the imported Scryfall catalog too
broadly for the app’s add-card workflow. In practice, users expect search to
return playable cards they can add to an inventory, not tokens, art cards,
front-card helpers, stickers, or other non-playable catalog objects.

That mismatch makes the search UI feel noisy and misleading. The frontend can
show grouped card names and printing pickers, but it should not have to guess
which catalog rows are “real cards” from incomplete response data.

Endpoint involved:

- `GET /cards/search`
- `GET /cards/search/names`

Current behavior:

The search responses expose only a narrow card summary shape and do not include
enough classification data for the frontend to reliably filter non-playable
objects on its own.

The backend search logic currently searches `mtg_cards` broadly without a
playable-card filter in `src/mtg_source_stack/inventory/catalog.py`.

Examples from the current imported full catalog show that non-playable objects
sit in the same search corpus as playable cards:

- search term `food` matches rows like `Food` with type line `Token Artifact —
  Food`
- search term `treasure` matches rows like `Dinosaur // Treasure`, `Merfolk //
  Treasure`, and `Pirate // Treasure` with token-oriented type lines

The database does already store `type_line`, but the current search responses
do not expose it and the current search endpoints do not filter on it.

Requested change:

Please make the default app-facing card search behavior playable-card-first.

Preferred behavior for v1:

1. `GET /cards/search` should exclude non-playable catalog objects by default.
2. `GET /cards/search/names` should also exclude non-playable catalog objects
   by default.
3. If backend wants to preserve broader catalog access for future tooling,
   expose that through an explicit opt-in query flag later rather than the
   default app behavior.

Examples of rows that should not appear by default in the app search flow:

- tokens
- art cards
- front-card helper rows
- stickers
- emblems
- other non-playable catalog objects that are not intended to be inventory
  additions in the normal card-add flow

Implementation note:

The short-term backend fix could use currently stored fields such as
`type_line`. A stronger long-term fix would store and use richer upstream
classification fields from Scryfall so the filter is explicit and durable.

Example request JSON:

`GET` endpoints have no request body.

Example response JSON:

The response shape does not need to change for the frontend to benefit from the
default filtering. The main requested behavior change is that the returned rows
represent playable cards by default.

Expected error cases:

- no new error envelope is required for the default filter behavior
- if backend later adds an opt-in broad-search flag, invalid flag values should
  follow the existing `400 validation_error` contract

Compatibility note:

Behavior-changing for default search results. To reduce compatibility risk,
backend may optionally preserve the current broader catalog search behind an
explicit opt-in query parameter while making the app-default behavior return
playable cards only.
