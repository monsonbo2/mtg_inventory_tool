## Frontend Backend Request

Related GitHub issue: [#39](https://github.com/monsonbo2/mtg_inventory_tool/issues/39)

Feature / screen:

- local-app first-run onboarding
- card search quick-add printing resolution

Current blocker:

- The repo is drifting toward a local-app setup, but the backend-supported
  first-run path is still framed mainly as a shared-service bootstrap flow.
  The frontend can create inventories manually today, but there is no clearly
  supported, idempotent local-first way to say "ensure this local install has a
  primary collection and open it".
- In quick-add search, the frontend wants to keep the printing picker
  unselected while still using the backend's default add choice if the user
  clicks Add immediately. To preserve that behavior and still know whether to
  expose other-language choices, the current UI ends up loading the full
  all-language printing list eagerly for the active card. That will get
  noticeably heavier as the app moves from demo data to real local catalogs.

Endpoint involved:

- `POST /me/bootstrap`
- `GET /cards/oracle/{oracle_id}/printings`

Current behavior:

- `POST /me/bootstrap` is documented as the intended first-run escape hatch for
  authenticated shared-service users. In local-demo mode, the app still
  supports ordinary `POST /inventories`, but the local-first semantics of
  `/me/bootstrap` are not the main documented story.
- `GET /cards/oracle/{oracle_id}/printings` returns printing rows and supports
  `lang` and `scope`. The frontend can request `lang=all`, but that is a
  detail-heavy response shape when the UI only needs:
  - the default add choice
  - whether English is available
  - whether other languages exist
  - the smaller initial printing set for the default quick-add path

Requested change:

- Clarify and support a deterministic local-first bootstrap contract. Any of
  these additive options would work:
  - make `POST /me/bootstrap` explicitly supported and documented for local app
    startup as an idempotent "ensure my default collection exists" flow
  - add a dedicated local-safe bootstrap / ensure-default-inventory route
  - publish stronger contract guidance that local installs should use a
    different supported bootstrap path instead of inheriting shared-service
    wording
- Add a lighter-weight printing lookup mode for quick-add, while preserving the
  existing full lookup route for explicit printing browsing. Any of these
  additive shapes would work:
  - a dedicated default-printing route for an `oracle_id`
  - additive query params on `/cards/oracle/{oracle_id}/printings` that return
    only the default / preferred subset first
  - a summary response that exposes the default add choice plus language
    availability before the frontend asks for every printing

Example request JSON:

```json
POST /me/bootstrap
```

```json
GET /cards/oracle/{oracle_id}/printings?lang=en
```

Example response JSON:

```json
{
  "created": false,
  "inventory": {
    "inventory_id": 12,
    "slug": "collection",
    "display_name": "Collection",
    "description": null
  }
}
```

```json
{
  "oracle_id": "bolt-oracle",
  "default_printing": {
    "scryfall_id": "bolt-m11",
    "lang": "en",
    "is_default_add_choice": true
  },
  "available_languages": ["en", "ja"],
  "has_more_printings": true,
  "printings": [
    {
      "scryfall_id": "bolt-m11",
      "name": "Lightning Bolt",
      "set_code": "m11",
      "set_name": "Magic 2011",
      "collector_number": "146",
      "lang": "en",
      "rarity": "common",
      "finishes": ["normal", "foil"],
      "tcgplayer_product_id": "1001",
      "image_uri_small": null,
      "image_uri_normal": null,
      "is_default_add_choice": true
    }
  ]
}
```

Expected error cases:

- `400` validation if a new printing-lookup mode or query-parameter
  combination is invalid
- `401` / `403` should keep the current shared-service auth behavior where
  applicable
- `404` when the requested `oracle_id` does not exist
- local-first bootstrap should be idempotent rather than returning a conflict
  for an already-initialized install

Compatibility note:

- additive
