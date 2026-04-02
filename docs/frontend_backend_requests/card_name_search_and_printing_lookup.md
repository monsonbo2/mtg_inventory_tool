# Frontend Backend Request: Card-Name Search And Printing Lookup

Status: Proposed
Owner: Unassigned
GitHub issue: [#16](https://github.com/monsonbo2/mtg_inventory_tool/issues/16)
Implementation PR: Not linked yet
Last updated: 2026-04-02

## Frontend Backend Request

Feature / screen:

Search and add flow for grouped card-name results with a second-step printing
picker

Current blocker:

The current search contract is printing-first. `GET /cards/search` returns one
row per printing, and the frontend currently caps that search to a small result
set.

That works for users who already know the exact printing they want, but it is a
poor fit for the intended search UX. In practice, users search by card name
first, then pick a printing only after they have drilled into the card.

For example, searching `lightning` should primarily surface distinct card names
such as `Lightning Bolt`, `Lightning Blast`, and `Lightning Helix`. It should
not lead with many `Lightning Bolt` printings followed by many `Lightning
Blast` printings.

The frontend can fake part of this in the local demo by fetching more
printing-level rows and grouping them client-side, but that is not a good
rollout contract for larger inventories or richer catalog search.

Endpoint involved:

- current: `GET /cards/search`
- requested additive support:
  - either a new name-level search endpoint such as `GET /cards/search/names`
  - or a new query mode on `GET /cards/search`
  - plus a dedicated printing lookup endpoint keyed by a stable card-level
    identifier such as `oracle_id`

Current behavior:

Today `GET /cards/search` returns printing rows with printing-specific identity
and metadata such as `scryfall_id`, `set_code`, `collector_number`, `lang`, and
`finishes`.

Example current response:

```json
[
  {
    "scryfall_id": "demo-bolt-alpha",
    "name": "Lightning Bolt",
    "set_code": "lea",
    "set_name": "Limited Edition Alpha",
    "collector_number": "161",
    "lang": "en",
    "rarity": "common",
    "finishes": ["normal"],
    "tcgplayer_product_id": "1001",
    "image_uri_small": "https://img.example/bolt-alpha-sm.jpg",
    "image_uri_normal": "https://img.example/bolt-alpha.jpg"
  },
  {
    "scryfall_id": "demo-bolt-m11",
    "name": "Lightning Bolt",
    "set_code": "m11",
    "set_name": "Magic 2011",
    "collector_number": "146",
    "lang": "en",
    "rarity": "common",
    "finishes": ["normal", "foil"],
    "tcgplayer_product_id": "1002",
    "image_uri_small": "https://img.example/bolt-m11-sm.jpg",
    "image_uri_normal": "https://img.example/bolt-m11.jpg"
  }
]
```

That shape is still useful for the eventual printing picker, but it is the
wrong primary result shape for name-first search.

Requested change:

Please add an additive two-step search contract for frontend rollout:

1. Name-level search results

Return distinct card-name results instead of distinct printings. Each result
should include a stable card-level identifier so the frontend can request the
available printings next.

Preferred fields for each name-level result:

- `oracle_id` or another stable card-level identifier
- `name`
- `image_uri_small`
- `image_uri_normal`
- optional helper metadata such as `printings_count`, `latest_set_code`, or
  `latest_set_name`

2. Printing lookup for a selected card

Given the stable card-level identifier from step 1, return the available
printings as printing rows suitable for the existing quick-add form.

Preferred behavior:

- printing rows should keep the existing `CatalogSearchRow` fields where
  possible
- printings should be sortable in a predictable way, for example newest first
- the endpoint should support normal filtering by language or finish when
  useful, but that is optional for v1

The current printing-level `GET /cards/search` behavior should remain available
for existing clients.

Example request JSON:

`GET` endpoints have no request body.

Example response JSON:

Example name-level response:

```json
[
  {
    "oracle_id": "demo-bolt-oracle",
    "name": "Lightning Bolt",
    "printings_count": 27,
    "image_uri_small": "https://img.example/bolt-sm.jpg",
    "image_uri_normal": "https://img.example/bolt.jpg"
  },
  {
    "oracle_id": "demo-blast-oracle",
    "name": "Lightning Blast",
    "printings_count": 9,
    "image_uri_small": "https://img.example/blast-sm.jpg",
    "image_uri_normal": "https://img.example/blast.jpg"
  }
]
```

Example printing lookup response:

```json
[
  {
    "scryfall_id": "demo-bolt-alpha",
    "name": "Lightning Bolt",
    "set_code": "lea",
    "set_name": "Limited Edition Alpha",
    "collector_number": "161",
    "lang": "en",
    "rarity": "common",
    "finishes": ["normal"],
    "tcgplayer_product_id": "1001",
    "image_uri_small": "https://img.example/bolt-alpha-sm.jpg",
    "image_uri_normal": "https://img.example/bolt-alpha.jpg"
  },
  {
    "scryfall_id": "demo-bolt-m11",
    "name": "Lightning Bolt",
    "set_code": "m11",
    "set_name": "Magic 2011",
    "collector_number": "146",
    "lang": "en",
    "rarity": "common",
    "finishes": ["normal", "foil"],
    "tcgplayer_product_id": "1002",
    "image_uri_small": "https://img.example/bolt-m11-sm.jpg",
    "image_uri_normal": "https://img.example/bolt-m11.jpg"
  }
]
```

Expected error cases:

- `400 validation_error` for blank or malformed search input
- `404 not_found` if a printing-lookup request targets a card-level identifier
  that does not exist
- current search error behavior for schema-not-ready and internal failures
  should remain unchanged

Compatibility note:

Additive. The frontend is asking for additional name-grouped search and
printing-lookup support without removing the current printing-level search
contract.
