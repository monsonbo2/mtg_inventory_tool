# Frontend Backend Request: Bulk Inventory Item Mutations

This supporting note preserves the original request plus the current shipped
bulk-mutation contract. The backend now exposes
`POST /inventories/{inventory_slug}/items/bulk` on the final generic route
shape, and the shipped operation set is broader than the original tag-only
MVP:

- `add_tags`
- `remove_tags`
- `set_tags`
- `clear_tags`
- `set_quantity`
- `set_notes`
- `set_acquisition`
- `set_finish`
- `set_location`
- `set_condition`

The live mutation remains transactional and all-or-nothing. Merge-capable
operations reuse the same `merge` / `keep_acquisition` semantics as the
single-item mutation paths, and frontend clients should refetch rows after
successful merge-capable bulk updates.

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
- the public route and envelope should be generic from day one
- the first implemented operation family should cover bulk tag actions for
  selected rows

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
- do not require per-item partial-success details in the first shipped version

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
  "updated_count": 3
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

## Backend Recommendation

Use the final generic bulk route now, but limit the first implemented
operations to bulk tag mutations.

That means:

- ship `POST /inventories/{inventory_slug}/items/bulk` as the long-term route
- ship a generic request/response envelope now
- implement only tag operations in the first backend slice
- add additional bulk mutation families later without replacing the route or
  reworking the public contract

This avoids a throwaway tag-only endpoint such as `/items/bulk-tags`, while
still keeping the first implementation small enough to ship safely.

## Proposed Web-V1 Contract

### Route

- `POST /inventories/{inventory_slug}/items/bulk`

### Auth

- use the same inventory-scoped write access as other write routes
- expected shared-service behavior:
  - inventory `editor` or `owner`
  - or global `admin`

### Request model

Suggested API model name:

- `BulkInventoryItemMutationRequest`

Suggested initial schema:

```json
{
  "operation": "add_tags",
  "item_ids": [12, 27, 44],
  "tags": ["commander", "trade"]
}
```

Suggested request fields:

- `operation`
  - initial supported values:
    - `add_tags`
    - `remove_tags`
    - `set_tags`
    - `clear_tags`
- `item_ids`
  - non-empty array of integer item ids
  - values must be unique
  - all ids must belong to the inventory in the route path
- `tags`
  - required for `add_tags`, `remove_tags`, and `set_tags`
  - forbidden for `clear_tags`

Suggested first-pass limits:

- reject empty `item_ids`
- reject duplicate `item_ids`
- cap `item_ids` to a reasonable max such as `100` or `200`

Suggested Pydantic shape:

```python
class BulkInventoryItemMutationRequest(ApiBaseModel):
    operation: Literal["add_tags", "remove_tags", "set_tags", "clear_tags"]
    item_ids: list[int]
    tags: list[str] | None = None
```

### Response model

Suggested API model name:

- `BulkInventoryItemMutationResponse`

Suggested response shape:

```json
{
  "inventory": "personal",
  "operation": "add_tags",
  "requested_item_ids": [12, 27, 44],
  "updated_item_ids": [12, 27, 44],
  "updated_count": 3
}
```

Suggested response fields:

- `inventory`
- `operation`
- `requested_item_ids`
- `updated_item_ids`
- `updated_count`

Do not include partial-success fields in v1. If partial batch behavior is ever
added later, it should be introduced explicitly rather than silently changing
the semantics of the first shipped contract.

### Transaction semantics

Recommended behavior:

- all-or-nothing transaction
- if validation or lookup fails, no rows are updated
- if any requested item id is invalid for the inventory, reject the entire
  batch

Recommended HTTP behavior:

- `400 validation_error`
  - empty `item_ids`
  - duplicate `item_ids`
  - unsupported `operation`
  - missing `tags` when required
  - `tags` supplied for `clear_tags`
- `404 not_found`
  - inventory does not exist
  - one or more `item_ids` do not belong to the inventory
- `403 forbidden`
  - authenticated user lacks inventory write access
- `409 conflict`
  - reserve for later bulk operation families that can collide with row
    identity or concurrent writes

For the initial tag-only implementation, `409` should usually not be needed.

### Audit semantics

Recommended behavior:

- write one audit event per affected item
- keep the current item-level audit model
- use the shared request id to group related events
- include bulk-specific metadata on each event

Suggested metadata shape:

```json
{
  "bulk_operation": true,
  "bulk_kind": "add_tags",
  "bulk_count": 3
}
```

This keeps audit behavior compatible with the existing audit feed and avoids
inventing a second parallel batch-audit contract.

## How The Later Generic Framework Builds On This

If the first implementation uses the final generic route and envelope, the
later generic framework is mostly additive work rather than a reset.

Pieces that should stay stable:

- route: `POST /inventories/{inventory_slug}/items/bulk`
- auth model
- `operation` + `item_ids` request envelope
- transaction wrapper
- response envelope
- audit grouping strategy
- OpenAPI and contract-artifact location

Pieces that expand later:

- broader `operation` union
- dispatcher from `operation` to handler
- operation-specific validation helpers
- operation-specific service handlers
- operation-specific conflict semantics

Suggested future expansion order:

1. tag operations
2. notes operations
3. location / condition / finish operations
4. quantity operations
5. acquisition operations

That order is recommended because location, condition, and finish are the first
bulk families likely to trigger row-identity collisions or merge semantics.

## Debt Guidance

This phased approach should not materially increase later work if these
constraints are kept:

- do not create a separate tag-only route
- do not make the public request/response models tag-specific
- do not ship partial-success semantics first if the intended long-term model
  is all-or-nothing
- do not create batch-audit records that replace or bypass existing item-level
  audit entries

If those constraints are followed, the first bulk-tag slice is mainly phased
delivery, not architectural debt.

## Suggested Implementation Slice

Primary files likely involved:

- `src/mtg_source_stack/api/request_models.py`
- `src/mtg_source_stack/api/response_models.py`
- `src/mtg_source_stack/api/routes.py`
- `src/mtg_source_stack/inventory/service.py`
- `src/mtg_source_stack/inventory/mutations.py`
- `tests/test_inventory_service.py`
- `tests/test_web_api.py`
- `tests/test_api_contract.py`
- `contracts/openapi.json`
- `docs/api_v1_contract.md`

Suggested backend tasks:

1. add bulk request/response API models
2. add one bulk route on the final generic path
3. add a service/mutation helper for bulk tag operations
4. enforce all-or-nothing validation and lookup behavior
5. write one audit event per touched item with bulk metadata
6. publish OpenAPI and contract-doc updates

## Test Checklist

Service layer:

- successful `add_tags`
- successful `remove_tags`
- successful `set_tags`
- successful `clear_tags`
- duplicate `item_ids` rejected
- empty `item_ids` rejected
- invalid/missing `tags` rejected
- unknown item id rejected
- item from another inventory rejected
- transaction rollback leaves all rows unchanged when the batch fails
- audit entries written for every updated item with shared bulk metadata

API layer:

- happy path returns `200` with the expected response envelope
- unauthorized caller gets `401`
- authenticated non-writer gets `403`
- missing inventory or mismatched item ids get `404`
- validation failures get `400` with the standard error envelope
- OpenAPI publishes the new request/response models and stays in parity with
  `contracts/openapi.json`

Contract/docs:

- update `docs/api_v1_contract.md`
- refresh `contracts/openapi.json`
- add one example payload under `contracts/demo_payloads/` for the initial bulk
  request and response
