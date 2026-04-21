## Frontend Backend Request

Related GitHub issue: [#39](https://github.com/monsonbo2/mtg_inventory_tool/issues/39)

Feature / screen:

- local-app first-run onboarding
- card search quick-add printing resolution

Current status after rescope:

- The local/shared first-run path is now covered by `GET /me/access-summary`
  plus idempotent `POST /me/bootstrap`. That part of the original request is
  treated as satisfied and should not gain another competing bootstrap route.
- The remaining backend contract need is a lightweight quick-add printing
  summary so the frontend can get the default add choice, language availability,
  and primary/preferred printings without using the full all-language printing
  lookup.

Endpoint involved:

- `GET /me/access-summary`
- `GET /cards/oracle/{oracle_id}/printings`
- `GET /cards/oracle/{oracle_id}/printings/summary`

Current behavior:

- `GET /me/access-summary` is the startup probe for onboarding-state decisions,
  and `POST /me/bootstrap` creates or returns one default `Collection` for an
  eligible caller.
- `GET /cards/oracle/{oracle_id}/printings` returns printing rows and supports
  `lang` and `scope`. Omitting `lang` already returns the default primary
  language subset, and `lang=all` remains the explicit full-browse expansion.

Requested change:

- Add a backend/API quick-add printing summary endpoint while preserving the
  existing full lookup route for explicit printing browsing:
  - `GET /cards/oracle/{oracle_id}/printings/summary`
  - return the backend default add choice when one exists
  - return `available_languages` across all scoped printings
  - return `printings_count` and `has_more_printings`
  - return the primary/preferred `printings` subset that is suitable for the
    quick-add picker
  - keep full all-language browsing on `GET /cards/oracle/{oracle_id}/printings?lang=all`

Example requests:

```http
GET /me/access-summary
```

```http
GET /cards/oracle/{oracle_id}/printings/summary
```

Example response JSON:

```json
{
  "can_bootstrap": true,
  "has_readable_inventory": false,
  "visible_inventory_count": 0,
  "default_inventory_slug": null
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
  "printings_count": 27,
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

- `400` validation if `scope` is invalid
- `401` / `403` should keep the current shared-service auth behavior where
  applicable
- `404` when the requested `oracle_id` does not exist

Compatibility note:

- additive
