# Frontend Backend Request: Inventory Transfer API

Status: Done
Owner: Boyd
GitHub issue: [#30](https://github.com/monsonbo2/mtg_inventory_tool/issues/30)
Implementation PR: Commits `c8c042f`, `537de8e`
Last updated: 2026-04-06

## Frontend Backend Request

Feature / screen:

Inventory-to-inventory actions such as copy selected rows, move selected rows,
and eventually duplicate or merge inventories.

Current blocker:

Resolved. The backend now owns this workflow directly instead of forcing the
frontend to emulate copy/move by chaining row reads, adds, and deletes.

Endpoint involved:

- `POST /inventories/{source_inventory_slug}/transfer`
- `POST /inventories/{source_inventory_slug}/duplicate`

Current behavior:

- `dry_run=true` returns a structured plan without mutating either inventory
- live mutations are transactional and all-or-nothing
- transfer supports both selected rows and whole-inventory transfer
- transfer supports `mode: copy | move`
- transfer supports `on_conflict: fail | merge`
- transfer uses explicit `keep_acquisition` merge policy instead of the older
  `metadata_policy` sketch
- whole-inventory previews can truncate returned per-row `results`, but summary
  counts remain authoritative
- transfer audit rows are grouped under one request correlation id
- duplication now builds on the same transfer engine to create a new inventory
  atomically and copy all source rows into it
- `shared_service` validates write access to both source and target inventories

Compatibility note:

Additive. This shipped as new routes and did not change existing add, patch,
delete, or bulk-mutation behavior.
