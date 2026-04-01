# Frontend Backend Request: Card Image Fields For Visual UI

Status: Proposed
Owner: Unassigned
GitHub issue: Not linked yet
Implementation PR: Not linked yet
Last updated: 2026-04-01

## Frontend Backend Request

Feature / screen:

Card search results, owned-item cards, and richer visual inventory layouts

Current blocker:

The current frontend-facing card payloads expose identifiers and set metadata,
but not image URLs. That is enough for a table-first UI, but it blocks a more
visual demo experience unless the frontend reaches outside the published
contract for card images.

Without image fields in the API contract, the frontend must either:

- stay text-only, or
- introduce a second unofficial card-data lookup path just for images

Endpoint involved:

- `GET /cards/search`
- `GET /inventories/{inventory_slug}/items`

Current behavior:

- search responses return card identity, set metadata, rarity, finishes, and
  selected IDs
- owned-item responses return inventory and pricing fields
- neither response currently includes card image URLs

Requested change:

Add card image fields to the frontend-facing response contract for at least
search results, and ideally owned inventory rows as well.

Preferred implementation:

- add one or more image URL fields such as `image_uri_small` and
  `image_uri_normal`
- if full image support is too large for web-v1, one thumbnail-sized field is
  still enough to unblock a visual local demo
- publish the new fields in `contracts/openapi.json` and example payloads

Example request JSON:

`GET /cards/search?query=Lightning%20Bolt` has no request body.

Example response JSON:

```json
[
  {
    "scryfall_id": "api-card-1",
    "name": "Lightning Bolt",
    "set_code": "lea",
    "set_name": "Limited Edition Alpha",
    "collector_number": "161",
    "lang": "en",
    "rarity": "common",
    "finishes": [
      "normal",
      "foil"
    ],
    "tcgplayer_product_id": null,
    "image_uri_small": "https://example.test/cards/lightning-bolt-small.jpg",
    "image_uri_normal": "https://example.test/cards/lightning-bolt-normal.jpg"
  }
]
```

Expected error cases:

- same existing `400`, `404`, `503`, and `500` behavior as the current search
  and owned-item routes
- absent images, if possible, should be represented consistently rather than
  forcing clients to guess

Compatibility note:

Additive. This request extends existing response payloads with optional visual
metadata for richer frontend demos.
