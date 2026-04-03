# Frontend Backend Request: Playable Card Search Scope

Status: Done
Owner: Boyd
GitHub issue: [#22](https://github.com/monsonbo2/mtg_inventory_tool/issues/22)
Implementation PR: Commits `b58f089`, `c1a5976`, `49f333e`
Last updated: 2026-04-02

## Frontend Backend Request

Feature / screen:

Search and add flow for the default inventory add experience

Current blocker:

The original catalog search routes treated the full local catalog as one broad
search space. That meant the default add flow could surface auxiliary catalog
objects such as tokens, emblems, art-series rows, and other non-mainline
results.

That behavior was noisy for the normal add-card experience, but the frontend
also still needed a way to intentionally search the broader local catalog when
the user actually wants those auxiliary objects.

Endpoint involved:

- `GET /cards/search`
- `GET /cards/search/names`
- `GET /cards/oracle/{oracle_id}/printings`

Current behavior:

The backend now supports two explicit catalog scopes:

- default behavior: mainline card-add flow
- additive opt-in: `scope=all`

Requested change:

1. Narrow the default app-facing search behavior to the mainline add flow.
2. Keep broad local-catalog search available as an explicit opt-in.
3. Keep grouped name search and oracle printings lookup internally consistent
   with the chosen scope.

Example request JSON:

`GET` endpoints have no request body.

Example request URLs:

```text
GET /cards/search?query=ajani
GET /cards/search?query=ajani&scope=all
GET /cards/search/names?query=ajani&scope=all
GET /cards/oracle/<oracle_id>/printings?scope=all
```

Expected error cases:

- `400 validation_error` for blank search input
- `400 validation_error` for unsupported `scope` values
- `404 not_found` if oracle printing lookup finds no matching rows in the
  requested scope

Compatibility note:

Mixed:

- behavior-changing for the default app-facing search behavior
- additive for the new explicit `scope=all` opt-in

## Resolution

The backend now:

- stores durable Scryfall classification fields on `mtg_cards`
- derives and persists `is_default_add_searchable`
- defaults app-facing search routes to the mainline add-flow scope
- exposes `scope=all` on:
  - `GET /cards/search`
  - `GET /cards/search/names`
  - `GET /cards/oracle/{oracle_id}/printings`
- keeps grouped name search metadata aligned with the selected scope:
  - `printings_count`
  - `available_languages`
  - representative row/image selection

The published contract lives in:

- `docs/api_v1_contract.md`
- `contracts/openapi.json`

## Frontend Follow-Up Still Needed

Backend support is done, but frontend integration still needs product/UI
choices.

Recommended frontend follow-up:

1. Keep ordinary typeahead and primary add-flow search on the default scope.
2. Add an explicit advanced or fallback affordance before calling
   `scope=all`.
3. When the UI opts into `scope=all`, keep that scope consistent across:
   - printing-first search
   - grouped card-name search
   - oracle printings lookup
4. Do not silently switch the normal add flow to `scope=all`, or the original
   auxiliary-row noise problem returns.

## Operational Note

On upgraded pre-`0008` databases, operators should run a fresh Scryfall bulk
import after migrating so the persisted default search scope matches fresh
import classification rather than older `type_line` backfill heuristics.
