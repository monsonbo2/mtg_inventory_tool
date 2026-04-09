# Frontend Backend Request: Expanded Frontend Demo Seed Data

Related GitHub issue: [#10](https://github.com/monsonbo2/mtg_inventory_tool/issues/10)

## Frontend Backend Request

Feature / screen:

Inventory selector, empty states, filter demos, mutation demos, and recent
activity screens

Current blocker:

The current frontend demo bootstrap is useful for basic API plumbing, but it is
too small to cover several demo UI states cleanly.

Today the seeded dataset is centered on one inventory with a narrow set of
items. That makes it harder to build and demo:

- inventory switching between multiple inventories
- empty inventory states
- richer filter combinations
- more than one audit history pattern
- rows with varied condition, finish, language, and note/tag states

Endpoint involved:

- `GET /inventories`
- `GET /inventories/{inventory_slug}/items`
- `GET /inventories/{inventory_slug}/audit`
- backend-owned demo data bootstrap via `scripts/bootstrap_frontend_demo.py`

Current behavior:

- the frontend bootstrap produces a small deterministic local dataset
- `GET /inventories` is effectively a single-inventory demo in the default flow
- the seeded rows are enough for smoke testing, but not enough for stronger UI
  demo coverage

Requested change:

Expand the backend-owned demo bootstrap dataset so frontend work has a richer
deterministic local demo by default.

Preferred additions:

- at least two inventories
- one inventory with rows and one intentionally sparse or empty inventory
- rows covering multiple finishes and conditions
- at least one row with notes and one without
- at least one row with tags and one with cleared tags
- enough audit history to make the recent activity view feel real

Example request JSON:

`GET /inventories` has no request body.

Example response JSON:

```json
[
  {
    "slug": "personal",
    "display_name": "Personal Collection",
    "description": "Main demo inventory",
    "item_rows": 42,
    "total_cards": 138
  },
  {
    "slug": "trade-binder",
    "display_name": "Trade Binder",
    "description": "Secondary demo inventory",
    "item_rows": 0,
    "total_cards": 0
  }
]
```

Expected error cases:

- no new route-level error behavior is required beyond the existing contract
- deterministic bootstrap behavior should remain operator-friendly for local
  setup and reset flows

Compatibility note:

Additive. This request improves local demo coverage without changing the
existing API surface.
