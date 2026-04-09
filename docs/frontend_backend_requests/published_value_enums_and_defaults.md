# Frontend Backend Request: Published Value Enums And Defaults

Related GitHub issue: [#8](https://github.com/monsonbo2/mtg_inventory_tool/issues/8)

## Frontend Backend Request

Feature / screen:

Add card form, quick edit controls, and inventory/search filters

Current blocker:

The frontend contract currently exposes fields such as `finish`,
`condition_code`, `language_code`, and search `lang` as plain strings in
OpenAPI. The backend enforces canonical values and defaults, but those allowed
values are not published clearly enough in the frontend-facing contract.

Without a published value list, the frontend has to either:

- hard-code values by reading backend implementation, or
- wait for `400` validation responses to discover invalid inputs

That makes it harder to build stable selects, filters, form validation, and
friendly error handling without reaching into backend internals.

Endpoint involved:

- `GET /cards/search`
- `GET /inventories/{inventory_slug}/items`
- `POST /inventories/{inventory_slug}/items`
- `PATCH /inventories/{inventory_slug}/items/{item_id}`

Current behavior:

- OpenAPI publishes these fields as strings rather than explicit enums
- Defaults are visible for some add-item fields, but the canonical allowed
  values are not fully documented
- The backend accepts and normalizes some aliases, but the contract does not
  say which values are canonical response values versus accepted input aliases

Requested change:

Publish canonical value sets and defaults in the frontend-facing contract for:

- `finish`
- `condition_code`
- `language_code`
- `lang` query filters where applicable

Preferred implementation:

- add enum metadata to relevant OpenAPI request and response schemas where
  possible
- document the canonical response values in `docs/api_v1_contract.md`
- document accepted input aliases when they differ from canonical response
  values

At minimum, the frontend needs a published answer for:

- canonical finish values such as `normal`, `foil`, and `etched`
- whether `nonfoil` is input-only and normalized to `normal`
- canonical condition codes
- canonical language codes
- default values used by add-item requests

Example request JSON:

```json
{
  "scryfall_id": "demo-bolt",
  "quantity": 2,
  "condition_code": "NM",
  "finish": "normal",
  "language_code": "en",
  "location": "Red Binder",
  "acquisition_price": "2.25",
  "acquisition_currency": "USD",
  "notes": null,
  "tags": [
    "burn",
    "trade"
  ]
}
```

Example response JSON:

```json
{
  "inventory": "personal",
  "card_name": "Lightning Bolt",
  "set_code": "lea",
  "set_name": "Limited Edition Alpha",
  "collector_number": "161",
  "scryfall_id": "demo-bolt",
  "item_id": 12,
  "quantity": 2,
  "finish": "normal",
  "condition_code": "NM",
  "language_code": "en",
  "location": "Red Binder",
  "acquisition_price": "2.25",
  "acquisition_currency": "USD",
  "notes": null,
  "tags": [
    "burn",
    "trade"
  ]
}
```

Expected error cases:

- `400` validation when the caller supplies a value outside the supported
  input set
- existing route-specific `404`, `409`, `503`, and `500` behavior should stay
  unchanged

Compatibility note:

Additive. This request publishes existing backend behavior more clearly without
requiring the frontend to infer allowed values from implementation code.
