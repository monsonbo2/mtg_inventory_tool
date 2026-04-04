# Frontend Backend Request: Inventory Transfer API

Status: Done
Owner: Boyd
GitHub issue: [#30](https://github.com/monsonbo2/mtg_inventory_tool/issues/30)
Implementation PR: Commits `c8c042f`, `537de8e`
Last updated: 2026-04-04

Resolved. The backend now exposes an atomic cross-inventory transfer API, and
the shipped surface is slightly stronger than the original proposed request.

Current implemented behavior:

- `POST /inventories/{source_inventory_slug}/transfer`
- supports `mode: copy | move`
- supports explicit `item_ids`
- also supports `all_items=true` for whole-inventory transfer
- supports `on_conflict: fail | merge`
- uses explicit `keep_acquisition` merge policy instead of the vaguer original
  `metadata_policy` sketch
- supports `dry_run=true` previews that reuse the same planner as live
  execution
- validates write access to both source and target inventories in
  `shared_service`
- keeps live mutations atomic and all-or-nothing

Related additive follow-on:

- `POST /inventories/{source_inventory_slug}/duplicate` now builds on the same
  transfer engine to create a new inventory atomically and copy all source rows
  into it

## Frontend Backend Request

Feature / screen:

Inventory-to-inventory actions such as copy selected rows, move selected rows,
and eventually duplicate or merge inventories.

Current blocker:

Resolved. The backend now owns this workflow directly instead of forcing the
frontend to emulate copy/move by chaining row reads, adds, and deletes.

Endpoint involved:

- `POST /inventories/{source_inventory_slug}/transfer`

Current behavior:

- `dry_run=true` returns a structured plan without mutating either inventory
- live mutations are transactional and all-or-nothing
- transfer supports both selected rows and whole-inventory transfer
- whole-inventory previews can truncate returned per-row `results`, but summary
  counts remain authoritative
- transfer audit rows are grouped under one request correlation id

Compatibility note:

Additive. This shipped as a new route and did not change existing add, patch,
delete, or bulk-mutation behavior.
