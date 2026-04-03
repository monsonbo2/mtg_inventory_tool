# Frontend Backend Request: Full-Catalog Demo Bootstrap Compatibility

Status: Proposed
Owner: Unassigned
GitHub issue: [#21](https://github.com/monsonbo2/mtg_inventory_tool/issues/21)
Implementation PR: Not linked yet
Last updated: 2026-04-02

## Frontend Backend Request

Feature / screen:

Local frontend demo setup against the real imported Scryfall catalog

Current blocker:

The documented full-catalog frontend demo bootstrap currently fails against the
real current Scryfall `default-cards` bulk file.

This is the documented setup flow:

```bash
python3 scripts/bootstrap_frontend_demo.py \
  --db var/db/frontend_demo.db \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json
```

Against the current official bulk file, the bootstrap aborts during curated
owned-row seeding with:

```text
mtg_source_stack.errors.ValidationError:
Finish 'foil' is not available for this card printing. Available finishes: normal.
```

That means the repo currently advertises a full-catalog demo mode that a
frontend contributor cannot use as documented.

Endpoint involved:

- backend-owned demo bootstrap via `scripts/bootstrap_frontend_demo.py`
- downstream frontend contract surfaces that depend on a working full-catalog
  demo DB:
  - `GET /cards/search/names`
  - `GET /cards/oracle/{oracle_id}/printings`
  - `GET /inventories`
  - `GET /inventories/{inventory_slug}/items`

Current behavior:

The small built-in demo bootstrap works.

The full-catalog mode imports the real `mtg_cards` catalog, but the curated
seed rows are not compatible with the current imported data.

Confirmed mismatches against the current official `default-cards` bulk file:

- `Lightning Bolt`, `lea`, `161`, `en` is nonfoil-only, but the bootstrap adds
  it as normal and then calls `set_finish(..., finish="foil")`
- `Swords to Plowshares`, `sta`, `10`, `ja` does not resolve in the current
  imported catalog
- `Sol Ring`, `cmr`, `334`, `en` does not resolve in the current imported
  catalog, while the intended etched demo state now matches a different real
  printing
- the current curated price snapshot rows also assume finish availability that
  no longer matches some of those printings

Requested change:

Please make the backend-owned full-catalog demo bootstrap deterministic and
compatible with the current real Scryfall catalog.

Two acceptable implementation shapes:

1. Update the hard-coded seeded printings to real current printings that
   satisfy the intended demo states.
2. Preferably, make the bootstrap resolve demo rows by constraints instead of
   by brittle hard-coded printings, for example:
   - English `Lightning Bolt` with foil support
   - English `Counterspell` normal-only
   - Japanese `Swords to Plowshares`
   - English `Sol Ring` with etched support

The second approach is more robust because the upstream catalog can drift over
time even when the demo intent stays the same.

Success criteria:

- the documented full-catalog bootstrap command completes successfully against
  the current official Scryfall `default-cards` bulk file
- it still produces the same intended frontend demo states:
  - multiple inventories
  - a curated non-empty `personal` inventory
  - mixed finishes, languages, notes, tags, acquisition states, and audit rows
- the resulting DB is usable immediately with `mtg-web-api --db
  var/db/frontend_demo.db`

Example request JSON:

This is backend-owned CLI/bootstrap work, so there is no HTTP request body for
the request itself. The relevant operator command is:

```bash
python3 scripts/bootstrap_frontend_demo.py \
  --db var/db/frontend_demo.db \
  --force \
  --full-catalog \
  --scryfall-json /path/to/default-cards.json
```

Example response JSON:

No new API response shape is required. The expected outcome is a successfully
bootstrapped demo DB whose existing API routes return valid data.

Expected error cases:

- invalid or missing `--scryfall-json` should keep the current CLI validation
- if the requested curated demo shape cannot be resolved from the imported
  catalog, the bootstrap should fail with a clear seed-resolution error instead
  of a later mutation mismatch
- normal import/SQLite failures should keep their current behavior

Compatibility note:

Non-breaking backend bug fix in backend-owned demo tooling. This request does
not ask for a new frontend API shape; it asks for the documented full-catalog
demo mode to work reliably against the real upstream data it claims to support.
