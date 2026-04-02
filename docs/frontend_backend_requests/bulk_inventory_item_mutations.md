# Frontend Backend Request: Bulk Inventory Item Mutations

Status: Proposed
Owner: Unassigned
GitHub issue: Not linked yet
Implementation PR: Not linked yet
Last updated: 2026-04-01

## Frontend Backend Request

Feature / screen:

Spreadsheet-style inventory table with multi-row selection and future bulk
actions

Current blocker:

The frontend can build a denser table view and multi-row selection UI with the
current read contract, but it cannot support clean bulk actions against the
current write contract.

Today, every mutation is item-specific:

- `PATCH /inventories/{inventory_slug}/items/{item_id}` targets exactly one
  item
- each PATCH request must specify exactly one mutation family
- there is no dedicated bulk-write endpoint for an explicit set of item IDs

That means a frontend bulk action such as "add this tag to all selected rows"
would otherwise need to:

- read each selected row's current tags in the client
- merge tags client-side
- issue one PATCH request per selected item
- handle partial failures item by item
- accept audit noise from many separate writes

That is workable as a temporary hack, but it duplicates backend-owned behavior
and creates a weak UX for the intended table workflow.

Endpoint involved:

- current single-item route:
  `PATCH /inventories/{inventory_slug}/items/{item_id}`
- missing route: dedicated bulk mutation endpoint for inventory items

Current behavior:

- `GET /inventories/{inventory_slug}/items` can already provide the rows a table
  view needs
- write operations remain item-by-item only
- single-item PATCH accepts exactly one mutation family such as quantity,
  finish, location, notes, or tags
- tag updates replace or clear tags for one item at a time

Requested change:

Add a dedicated bulk mutation endpoint that applies one mutation family to an
explicit list of `item_ids` in a single request, while keeping the existing
single-item PATCH route unchanged.

Preferred route shape:

- `POST /inventories/{inventory_slug}/items/bulk`

Preferred request semantics:

- one bulk operation per request
- explicit `item_ids` array supplied by the client
- operation-specific payload fields
- initial minimum support should cover bulk tag actions for selected rows

Preferred initial bulk operations:

- `add_tags`
- `remove_tags`
- `set_tags`
- `clear_tags`

Preferred response semantics:

- explicit `operation` discriminator
- `requested_item_ids`
- `updated_item_ids`
- `updated_count`
- optional skipped/error details if partial processing is allowed

Frontend preference:

- bulk tag operations should be transactional or otherwise clearly defined as
  all-or-nothing, so table-selection UX does not have to reconcile a partially
  applied batch by default

Example request JSON:

```json
{
  "operation": "add_tags",
  "item_ids": [12, 27, 44],
  "tags": ["commander", "trade"]
}
```

Example response JSON:

```json
{
  "inventory": "personal",
  "operation": "add_tags",
  "requested_item_ids": [12, 27, 44],
  "updated_item_ids": [12, 27, 44],
  "updated_count": 3,
  "skipped_item_ids": []
}
```

Expected error cases:

- `400` validation for:
  - empty `item_ids`
  - duplicate `item_ids`
  - unsupported `operation`
  - missing `tags` when the operation requires them
- `404` when the inventory does not exist or when one or more requested items
  do not belong to that inventory
- `409` if the backend chooses to reject a batch because it conflicts with
  another invariant or concurrent write
- existing `503` and `500` route behavior should remain consistent with the
  rest of the API

Compatibility note:

Additive. This request adds a dedicated bulk-write contract without changing the
existing single-item PATCH behavior.
