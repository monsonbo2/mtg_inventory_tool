## Frontend Backend Request

Status: Proposed
Owner: Unassigned
GitHub issue: [#30](https://github.com/monsonbo2/mtg_inventory_tool/issues/30)
Implementation PR: Not linked yet
Last updated: 2026-04-03

Feature / screen:

Inventory-to-inventory actions such as copy selected rows, move selected rows,
and eventually duplicate or merge inventories.

Current blocker:

The frontend can emulate cross-inventory copy or move by reading source rows,
posting them one by one to the target inventory, and then deleting source rows
for a move. That is workable for a demo, but it is not a clean product
implementation because the operation is not atomic, merge/conflict behavior is
implicit, and failures can leave partial state across two inventories.

Endpoint involved:

- Current related endpoints:
  - `GET /inventories`
  - `GET /inventories/{inventory_slug}/items`
  - `POST /inventories/{inventory_slug}/items`
  - `DELETE /inventories/{inventory_slug}/items/{item_id}`
- Requested new endpoint:
  - `POST /inventories/{source_inventory_slug}/transfer`

Current behavior:

- Source rows can be listed and destination rows can be created one at a time.
- Adds may merge into an existing destination row when printing, condition,
  finish, language, and location match.
- Notes and acquisition metadata can raise row-level conflicts during add.
- There is no dry-run summary for cross-inventory actions.
- There is no single API operation that models copy or move between
  inventories.
- Audit history would currently appear as many row-level add/delete events
  rather than one grouped transfer action.

Requested change:

Add an atomic cross-inventory transfer API that supports both copy and move.

Proposed request fields:

- `target_inventory_slug`: required
- `mode`: `copy` or `move`
- `item_ids`: list of source row ids to transfer
- optional future support: `all_items: true`
- `on_conflict`: `merge` or `fail`
- `metadata_policy`: explicit rule for source/target metadata when merging
- `dry_run`: when true, return what would happen without mutating

Expected behavior:

- Validate permissions on both source and target inventories before mutation.
- Execute the transfer atomically.
- For `move`, only remove source rows if the target-side work succeeds.
- Return a structured summary of copied, moved, merged, skipped, and failed
  rows.
- Group affected audit rows under one transfer/request correlation id.

Example request JSON:

```json
{
  "target_inventory_slug": "trade-binder",
  "mode": "copy",
  "item_ids": [101, 102, 103],
  "on_conflict": "merge",
  "metadata_policy": "preserve_source",
  "dry_run": false
}
```

Example response JSON:

```json
{
  "source_inventory_slug": "personal",
  "target_inventory_slug": "trade-binder",
  "mode": "copy",
  "requested_count": 3,
  "copied_count": 2,
  "moved_count": 0,
  "merged_count": 1,
  "skipped_count": 0,
  "failed_count": 0,
  "results": [
    { "item_id": 101, "status": "copied", "target_item_id": 2201 },
    { "item_id": 102, "status": "merged", "target_item_id": 2179 },
    { "item_id": 103, "status": "copied", "target_item_id": 2202 }
  ]
}
```

Expected error cases:

- `400` invalid request shape, unsupported `mode`, unsupported conflict policy,
  empty item list, or invalid source/target combination
- `403` caller lacks write access on either source or target inventory
- `404` source inventory, target inventory, or one of the requested item ids is
  not found
- `409` requested transfer conflicts with merge/metadata rules under
  `on_conflict: fail`
- `503` schema not ready

Compatibility note:

Additive. This should be a new endpoint that does not change existing add,
patch, delete, or tags-only bulk mutation behavior.
