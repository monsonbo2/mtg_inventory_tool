# Frontend Backend Request: CSV Import HTTP API

Status: Proposed
Owner: Unassigned
GitHub issue: [#25](https://github.com/monsonbo2/mtg_inventory_tool/issues/25)
Implementation PR: Not linked yet
Last updated: 2026-04-03

## Frontend Backend Request

Feature / screen:

CSV import flow in the web frontend

Current blocker:

The backend already has substantial CSV import functionality, but it is only
available through the CLI today.

The frontend cannot build a real CSV import experience against the current HTTP
contract because there is no API route for:

- uploading a CSV file
- previewing the import result
- committing the import
- returning structured row-level import feedback

Without an HTTP import surface, the frontend would have to reimplement CSV
parsing, row normalization, finish inference, identifier resolution, and
error/report behavior in the browser. That would duplicate backend business
logic that already exists in `src/mtg_source_stack/inventory/csv_import.py`.

Endpoint involved:

- requested additive endpoint:
  - preferred: `POST /imports/csv`

Current behavior:

Today the import flow exists in backend code and CLI only:

- CSV ingest/orchestration: `src/mtg_source_stack/inventory/csv_import.py`
- CLI command: `src/mtg_source_stack/cli/inventory.py` via `import-csv`

That path already supports important backend behaviors the frontend should not
reimplement:

- header normalization and alias handling
- inventory inference / default inventory behavior
- identifier resolution from `scryfall_id`, `oracle_id`, `tcgplayer_product_id`,
  or `name`
- finish inference when omitted and only one finish is valid
- row-number-specific validation failures
- dry-run behavior with report generation

Requested change:

Please expose the existing CSV import capability over HTTP in an additive way.

Preferred v1 shape:

`POST /imports/csv`

Preferred request form:

- `multipart/form-data`
- fields:
  - `file`: uploaded CSV file
  - `default_inventory`: optional default inventory slug when the CSV does not
    include an inventory column
  - `dry_run`: optional boolean, defaults to `false`

Preferred response behavior:

- when `dry_run=true`, validate and resolve the import using the real backend
  logic but do not persist changes
- when `dry_run=false`, persist changes and return the same style of structured
  report
- return a structured report that closely matches the existing CLI/import
  report shape where practical

Requested response fields:

- `csv_filename`
- `default_inventory`
- `rows_seen`
- `rows_written`
- `dry_run`
- `imported_rows`

Each `imported_rows` entry should include at least:

- `csv_row`
- the resolved mutation result fields already returned by add-card responses
  such as:
  - `inventory`
  - `card_name`
  - `set_code`
  - `set_name`
  - `collector_number`
  - `scryfall_id`
  - `item_id`
  - `quantity`
  - `finish`
  - `condition_code`
  - `language_code`
  - `location`
  - `notes`
  - `tags`

If backend prefers a two-endpoint flow instead, this would also work:

- `POST /imports/csv/preview`
- `POST /imports/csv/commit`

But a single endpoint with `dry_run` is likely the simplest way to reuse the
existing backend import flow.

Example request JSON:

This endpoint would use multipart upload rather than JSON.

Example response JSON:

```json
{
  "csv_filename": "inventory_import.csv",
  "default_inventory": "personal",
  "rows_seen": 3,
  "rows_written": 3,
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
- `400 validation_error` for row-level import failures, with messages that
  preserve row context similar to the current CLI/import behavior
- `404 not_found` if referenced identifiers or inventories do not exist
- current schema / internal error behavior should remain unchanged

Compatibility note:

Additive. This would expose existing backend import capability over HTTP
without removing or changing the current CLI import flow.
