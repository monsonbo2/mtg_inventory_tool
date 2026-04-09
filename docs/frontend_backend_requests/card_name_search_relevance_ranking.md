## Frontend Backend Request

Related GitHub issue: [#29](https://github.com/monsonbo2/mtg_inventory_tool/issues/29)

Feature / screen:

Card-name search autocomplete and grouped search results for the add-card flow.

Current blocker:

The frontend now preserves backend ordering for `GET /cards/search/names`, but
the current backend ranking is still mostly lexical. That means results can
feel technically correct while still not matching user intent for common MTG
queries. Users generally expect cards with higher play relevance or broader
recognition to appear ahead of obscure prefix matches.

Concrete example:

- query: `lightn`
- current backend-leading results can still include cards like `Lightning Angel`
  near the top because they are valid prefix matches
- users often expect cards like `Lightning Bolt` to outrank less relevant
  matches for this kind of query

Endpoint involved:

`GET /cards/search/names`

Potential follow-on endpoint:

`GET /cards/search`

Current behavior:

- backend ranks by exact match, then prefix match, then FTS/BM25 text score,
  then alphabetical name/date tie-breaks
- no popularity or play-relevance signal is stored in the current live catalog
  model
- frontend can preserve backend order, but it cannot infer real card relevance
  from the current response shape

Requested change:

Introduce backend-owned relevance ranking for card-name search so the default
result ordering better reflects what players are likely looking for.

Recommended direction:

- keep lexical match buckets first:
  - exact name
  - starts with query
  - other strong text matches
- within those buckets, add a popularity-aware tie-breaker
- use backend-owned catalog fields instead of frontend heuristics

Preferred implementation shape:

- ingest and store Scryfall popularity-oriented fields that are already present
  in bulk data, such as `edhrec_rank` and related ranking metadata when useful
- use those fields as additive tie-breakers after lexical match quality, not as
  replacements for lexical matching
- keep the response contract additive if possible; the first pass can improve
  ordering without adding new response fields

Optional future extension:

- expose a lightweight search score or ranking source for debugging/tuning
- support multiple ranking profiles later if product needs them

Example request JSON:

Not applicable. This is a GET route.

Example response JSON:

No shape change required for the first pass. Existing response rows are fine if
the backend ordering improves.

Expected error cases:

- no new error cases required
- current validation and not-found behavior should remain unchanged

Compatibility note:

Behavior-changing but non-breaking at the schema level. The response ordering
would change, but the route and payload shape can remain additive-compatible.
