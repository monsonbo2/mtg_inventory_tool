# Frontend Backend Request: PATCH Operation Contract Clarity

Status: Done
Owner: Steve
GitHub issue: [#9](https://github.com/monsonbo2/mtg_inventory_tool/issues/9)
Implementation PR: Not linked yet
Last updated: 2026-04-01

## Frontend Backend Request

Feature / screen:

Owned item quick edit, inline edit, and edit-modal save flows

Current blocker:

The current patch endpoint accepts a broad request model with many optional
fields, but runtime behavior only allows one mutation family per request.

That creates two frontend problems:

- a save flow that edits more than one field at once currently fails with
  `400` validation
- the `200` response shape changes by operation, but the current contract does
  not include an explicit discriminator field the frontend can branch on

The frontend can work around this by issuing one request per field and inferring
the response type from returned fields, but that is more brittle than it needs
to be.

Endpoint involved:

- `PATCH /inventories/{inventory_slug}/items/{item_id}`

Current behavior:

- request bodies may include many optional fields in schema
- runtime validation rejects requests that specify more than one mutation
  family
- responses are operation-specific shapes such as quantity, finish, location,
  condition, notes, tags, or acquisition updates

Requested change:

Keep the current single-mutation behavior if that is the intended web-v1 rule,
but make the contract more explicit and easier for clients to consume.

Preferred implementation:

- add an explicit response discriminator such as `operation`
- document that patch requests are single-mutation-only in
  `docs/api_v1_contract.md`
- publish one example request and response for each supported patch operation
  in `contracts/demo_payloads/`

Example request JSON:

```json
{
  "finish": "foil"
}
```

Example response JSON:

```json
{
  "operation": "set_finish",
  "inventory": "personal",
  "card_name": "Lightning Bolt",
  "set_code": "lea",
  "set_name": "Limited Edition Alpha",
  "collector_number": "161",
  "scryfall_id": "demo-bolt",
  "item_id": 12,
  "quantity": 2,
  "finish": "foil",
  "condition_code": "NM",
  "language_code": "en",
  "location": "Red Binder",
  "acquisition_price": "2.25",
  "acquisition_currency": "USD",
  "notes": null,
  "tags": [
    "burn",
    "trade"
  ],
  "old_finish": "normal"
}
```

Expected error cases:

- `400` validation when more than one mutation family is supplied in one
  request
- existing `404`, `409`, `503`, and `500` route behavior should stay unchanged

Compatibility note:

Additive if implemented through docs/examples plus an added discriminator field.
Behavior-changing only if the backend decides to support true multi-field patch
updates instead.

Resolution:

- PATCH remains single-mutation-only in web-v1
- patch responses now include an explicit `operation` discriminator
- demo payloads now include one request/response example for each supported
  patch family
