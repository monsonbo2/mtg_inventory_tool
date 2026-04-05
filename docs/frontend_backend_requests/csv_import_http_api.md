# Frontend Backend Request: CSV Import HTTP API

Status: Done
Owner: Boyd
GitHub issue: [#25](https://github.com/monsonbo2/mtg_inventory_tool/issues/25)
Implementation PR: Commits `69afeb7`..`9169928`, merged via `485f937`
Last updated: 2026-04-04

## Frontend Backend Request

Feature / screen:

CSV import flow in the web frontend

Current blocker:

Resolved. The backend now exposes `POST /imports/csv` and the frontend can
build directly against the HTTP contract.

Current implemented behavior:

- `POST /imports/csv`
- `multipart/form-data` request with `file`, optional `default_inventory`,
  optional `dry_run`, and optional `resolutions_json`
- dry-run preview plus commit through the same endpoint
- structured row-level preview feedback through `resolution_issues`
- `ready_to_commit` signaling for ambiguous rows
- `summary` payload with requested, imported, and unresolved quantity counts
- backend-side source-format detection via `detected_format`

The frontend no longer needs to reimplement CSV parsing, row normalization,
finish inference, identifier resolution, or source-specific CSV field mapping
in the browser.

Endpoint involved:

- additive endpoint now shipped:
  - `POST /imports/csv`

Implementation notes:

The route reuses the existing backend import engine plus source-specific CSV
adapters. The current first-party detectors are:

- `deckbox_collection_csv`
- `deckstats_collection_csv`
- `generic_csv`
- `manabox_collection_csv`
- `mtggoldfish_collection_csv`
- `mtgstocks_collection_csv`
- `tcgplayer_app_collection_csv`
- `tcgplayer_legacy_collection_csv`

The route keeps the backend-owned behaviors this request was originally asking
for:

- header normalization and alias handling
- inventory inference / default inventory behavior
- identifier resolution from `scryfall_id`, `oracle_id`,
  `tcgplayer_product_id`, or `name`
- finish inference when omitted and only one finish is valid
- row-number-specific validation failures
- dry-run behavior with report generation
- structured ambiguity suggestions instead of frontend-side guessing

Example request JSON:

This endpoint would use multipart upload rather than JSON.

Example response JSON:

```json
{
  "csv_filename": "inventory_import.csv",
  "detected_format": "tcgplayer_app_collection_csv",
  "default_inventory": "personal",
  "rows_seen": 3,
  "rows_written": 3,
  "ready_to_commit": true,
  "summary": {
    "total_card_quantity": 3,
    "distinct_card_names": 1,
    "distinct_printings": 1,
    "requested_card_quantity": 3,
    "unresolved_card_quantity": 0
  },
  "resolution_issues": [],
  "dry_run": true,
  "imported_rows": [
    {
      "csv_row": 2,
      "inventory": "personal",
      "card_name": "Lightning Bolt",
      "set_code": "lea",
      "set_name": "Limited Edition Alpha",
      "collector_number": "161",
      "scryfall_id": "demo-bolt",
      "item_id": 42,
      "quantity": 2,
      "finish": "normal",
      "condition_code": "NM",
      "language_code": "en",
      "location": "Blue Binder",
      "notes": "CSV import row",
      "tags": ["bulk import"]
    }
  ]
}
```

Expected error cases:

- `400 validation_error` for malformed CSV payloads, missing file upload, or
  invalid multipart fields
- `400 validation_error` for unresolved ambiguity on non-dry-run requests,
  with `error.details.resolution_issues`
- `400 validation_error` for row-level import failures, with messages that
  preserve row context similar to the current CLI/import behavior
- `404 not_found` if referenced identifiers or inventories do not exist
- current schema / internal error behavior should remain unchanged

Compatibility note:

Implemented additively. The HTTP route reuses the backend import capability
without removing or changing the current CLI import flow. Treat
`docs/api_v1_contract.md` and `contracts/openapi.json` as the canonical
current contract.
