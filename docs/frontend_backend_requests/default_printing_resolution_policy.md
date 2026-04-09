# Frontend Backend Request: Default Printing Resolution Policy

Related GitHub issue: [#23](https://github.com/monsonbo2/mtg_inventory_tool/issues/23)

This supporting note preserves the original request plus the current published
quick-add default printing policy. The backend now treats the `oracle_id`
resolution behavior below as stable contract behavior.

Current implemented behavior:

- quick-add by `oracle_id` stays inside the default add-flow catalog scope
- when `lang` is omitted, the resolver prefers English printings first
- within that pool, it prefers mainstream paper printings before newer
  promo-like rows
- omitted `finish` still defaults to `normal`
- explicit `language_code`, `set_code`, `collector_number`, and `finish`
  overrides still narrow resolution as before

The policy is now documented in the API contract and request-model field
descriptions, so the frontend can safely build a simplified quick-add path on
top of it.

## Frontend Backend Request

Feature / screen:

Quick add / card-level add flow

Current blocker:

The backend already accepts card-level `oracle_id` on
`POST /inventories/{inventory_slug}/items` and resolves that to a concrete
printing. That is the right long-term direction for the frontend because users
generally think in card names first, not exact printings first.

The problem is that the default printing choice is still effectively an
implementation detail rather than a documented product policy.

Today the resolver is deterministic, but the frontend cannot safely build a
simple “card name + quantity” add flow around it until the default-selection
behavior is explicitly defined and treated as contract-worthy behavior. If that
implicit choice is surprising, the frontend would be hiding an important
inventory decision from the user.

Endpoint involved:

- `POST /inventories/{inventory_slug}/items`
- specifically the `oracle_id` resolution path

Current behavior:

The add request model already accepts `oracle_id`.

The resolver currently orders matching printings roughly like this:

1. English printings first when available
2. Newer `released_at` first
3. then stable tie-break fields such as set code / collector number

When `language_code` is omitted, the stored owned-row language inherits the
resolved printing language.

This behavior is deterministic and already covered by tests, but it is not yet
framed as a stable product rule for frontend simplification.

Why this matters:

- a newest-English default can be technically valid but still unintuitive for
  real MTG users if it prefers a promo, bonus sheet, or otherwise odd printing
- the frontend should not remove explicit printing selection unless backend is
  intentionally committing to the fallback policy
- omitted `finish` currently defaults to `normal`, which also affects which
  printing can resolve successfully

Requested change:

Please define and publish the intended default printing resolution policy for
card-level add by `oracle_id`.

Preferred scope for this request:

1. Confirm whether the current `english-first, newest-first` behavior is the
   desired long-term product rule.
2. If not, replace it with a more product-driven default policy and document
   the precedence explicitly.
3. Publish that policy in the API/docs so frontend can rely on it when
   simplifying quick add.
4. Keep the existing explicit override path available for users who want to
   choose language, finish, or exact printing.
5. Clarify how omitted `finish` should interact with this resolution path for
   cards whose default practical printing would not be `normal`.

This request does not require removing exact-printing add. It is specifically
about making the fallback card-level add behavior intentional and safe to rely
on.

Example request JSON:

```json
{
  "oracle_id": "demo-bolt-oracle",
  "quantity": 1
}
```

Example response JSON:

```json
{
  "inventory": "personal",
  "card_name": "Lightning Bolt",
  "set_code": "m11",
  "set_name": "Magic 2011",
  "collector_number": "146",
  "scryfall_id": "demo-bolt-m11",
  "item_id": 42,
  "quantity": 1,
  "finish": "normal",
  "condition_code": "NM",
  "language_code": "en",
  "location": "",
  "acquisition_price": null,
  "acquisition_currency": null,
  "notes": null,
  "tags": []
}
```

Expected error cases:

- `404 not_found` when the provided `oracle_id` does not exist
- `400 validation_error` when the request includes an explicit finish or
  language override that cannot resolve to a compatible printing
- current collision / schema / internal error behavior should remain unchanged

Compatibility note:

Potentially behavior-changing if backend decides the current implicit
resolution order is not the desired long-term rule. The frontend is explicitly
asking for the policy to become intentional and documented before relying on it
as the default add path.
