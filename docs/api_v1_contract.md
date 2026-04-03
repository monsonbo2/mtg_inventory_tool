# API V1 Contract

This document defines the JSON and error-shaping rules the web layer should
preserve for the first API-backed version of the project.

## Response Shaping

- Service responses are serialized through
  `mtg_source_stack.inventory.response_models.serialize_response`.
- The FastAPI layer publishes explicit HTTP response models in OpenAPI rather
  than relying on inferred `Any` responses.
- Money values are emitted as decimal strings, not JSON numbers.
  Examples: `"2.5"` or `"2.50"`, but never the JSON number `2.5`.
- Absent optional values are emitted as `null`.
- Lists stay lists, including fields like catalog `finishes` and inventory
  `tags`.
- Catalog search rows and owned inventory rows may include optional visual
  fields such as `image_uri_small` and `image_uri_normal` when card image data
  is available.
- Card-name search rows include `available_languages` so the frontend can hint
  when alternate-language printings exist before fetching the full printing
  list.
- Owned inventory rows include `allowed_finishes` so edit UIs can constrain
  finish changes without doing an extra catalog lookup.
- Dates remain ISO-8601 strings. Audit timestamps are emitted in UTC with an
  explicit timezone suffix, for example `2026-04-01T20:41:10Z`.
- `PATCH /inventories/{inventory_slug}/items/{item_id}` accepts exactly one
  mutation family per request: quantity, finish, location, condition, notes,
  tags, or acquisition.
- `PATCH /inventories/{inventory_slug}/items/{item_id}` returns
  operation-specific result shapes rather than one generic mutation envelope.
- PATCH responses include an explicit `operation` discriminator such as
  `set_finish` or `set_quantity`; clients should branch on `operation` instead
  of inferring the result type from optional fields alone.
- `POST /inventories/{inventory_slug}/items/bulk` accepts exactly one bulk
  mutation operation per request and currently supports tag operations only:
  `add_tags`, `remove_tags`, `set_tags`, and `clear_tags`.
- Bulk item mutation responses use a stable envelope with `inventory`,
  `operation`, `requested_item_ids`, `updated_item_ids`, and `updated_count`.
- The current bulk tag implementation is transactional and all-or-nothing: if
  validation or item lookup fails, no rows in the batch are updated.
- Audit event `before`, `after`, and `metadata` fields remain intentionally
  loose JSON objects in web-v1.
- `GET /health` returns mode-oriented fields such as `status`,
  `auto_migrate`, and `trusted_actor_headers`; it does not expose the SQLite
  filesystem path in web-v1.

## Published Values And Defaults

- `finish`
  - canonical response values: `normal`, `foil`, `etched`
  - default request value: `normal`
  - accepted input alias: `nonfoil`, which is normalized to `normal`
- `condition_code`
  - canonical response values: `M`, `NM`, `LP`, `MP`, `HP`, `DMG`
  - default request value: `NM`
  - human-readable aliases such as `near mint` and `lightly played` are
    accepted and normalized
- `language_code`
  - commonly published canonical codes: `en`, `ja`, `de`, `fr`, `it`, `es`,
    `pt`, `ru`, `ko`, `zhs`, `zht`, `ph`
  - add-item requests inherit the resolved printing language when
    `language_code` is omitted
  - language-name aliases such as `english` and `japanese` are accepted and
    normalized
- `POST /inventories/{inventory_slug}/items`
  - accepts `scryfall_id`, `oracle_id`, `tcgplayer_product_id`, or exact
    `name` as identifier inputs
  - `oracle_id` resolves to one printing by backend policy rather than storing
    `oracle_id` directly on inventory rows
  - when `language_code` is omitted, the stored owned language inherits the
    resolved printing language
  - if `language_code` is explicitly provided and does not match the resolved
    printing language, the request returns `400 validation_error`
- `GET /cards/search` query `lang`
  - uses the same published language-code guidance as `language_code`
  - current search behavior still matches against the stored catalog language
    values rather than enforcing a strict enum at the HTTP layer
- `GET /cards/search` query `query`
  - must be non-empty after trimming whitespace
  - blank or whitespace-only search queries return `400 validation_error`
- `GET /cards/search/names`
  - groups results by `oracle_id`
  - prefers an English representative row and image when available
  - includes `available_languages` for the matched card
- `GET /cards/oracle/{oracle_id}/printings`
  - returns printing-level rows for one `oracle_id`
  - defaults to English printings when available
  - accepts `lang=all` to include all available catalog languages
  - accepts specific language codes such as `lang=ja` to request one language
- `POST /inventories/{inventory_slug}/items/bulk`
  - current supported operations: `add_tags`, `remove_tags`, `set_tags`,
    `clear_tags`
  - `item_ids` must be non-empty and unique
  - `tags` is required for `add_tags`, `remove_tags`, and `set_tags`
  - `tags` must be omitted for `clear_tags`
  - use `clear_tags` instead of sending an empty tag list

OpenAPI publishes these defaults and canonical values directly. For `finish`,
the request contract is strict enough to advertise the accepted input set. For
`condition_code` and `language_code`, the schema publishes defaults and
canonical guidance without pretending the current runtime is stricter than it
really is.

## Error Envelope

The API layer should return errors in this shape:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Human-readable explanation."
  }
}
```

## HTTP Error Mapping

- `AuthenticationError` -> `401`
- `ValidationError` -> `400`
- `NotFoundError` -> `404`
- `ConflictError` -> `409`
- `SchemaNotReadyError` -> `503`
- unexpected exceptions -> `500` with code `internal_error`
- The published OpenAPI contract suppresses FastAPI's default autogenerated
  `422` validation responses so the documented contract matches the runtime
  `400` validation envelope.

The message for unexpected exceptions should stay generic at the HTTP boundary:

```json
{
  "error": {
    "code": "internal_error",
    "message": "Internal server error."
  }
}
```

Unhandled exceptions should still be logged server-side with request context
before the generic 500 envelope is returned.

## Execution Model

- The JSON and error contract is the stable part of web-v1.
- The current API shell supports two runtime modes:
  - `local_demo`, the default local-first posture for UI and contract work
  - `shared_service`, a safer startup posture for a pre-migrated, single-host
    SQLite deployment
- The HTTP route boundary now uses sync route handlers to match the current
  synchronous inventory and SQLite-backed service layer.
- Broader transport/runtime guarantees are still intentionally modest and
  single-host scoped in web-v1.
- `shared_service` assumes a single-host SQLite deployment with WAL and
  busy-timeout configured by the shared connection layer.
- The recommended first-live browser deployment is same-origin through a reverse
  proxy that publishes `/api` publicly and strips that prefix before forwarding
  to the backend root-route surface.
- In `local_demo`, the API ignores caller-supplied `X-Actor-Id` values and
  records mutating audit entries with `actor_type="api"` and
  `actor_id="local-demo"`.
- For explicit local/dev testing in `local_demo`, setting
  `MTG_API_TRUST_ACTOR_HEADERS=true` allows non-empty `X-Actor-Id` header
  values to flow into audit attribution.
- `shared_service` disables auto-migrate by default. It should be started
  against a pre-migrated database and a single app process for now.
- In `shared_service`, every current app route except `/health` requires a
  verified upstream user header. The default header name is
  `X-Authenticated-User`, and it can be overridden with
  `MTG_API_AUTHENTICATED_ACTOR_HEADER`.
- In `shared_service`, the API also accepts a normalized roles header. The
  default header name is `X-Authenticated-Roles`, and it can be overridden with
  `MTG_API_AUTHENTICATED_ROLES_HEADER`.
- The current recognized global app roles are `editor` and `admin`.
- If the verified user header is present and the roles header is missing, the
  API defaults that caller to `editor`.
- `admin` implies `editor`.
- Shared-service inventory access is also scoped by local inventory
  memberships:
  - `viewer` can read a specific inventory
  - `editor` can read and write a specific inventory
  - `owner` can read and write a specific inventory
  - global `admin` bypasses inventory membership checks
- `GET /inventories` returns only the inventories visible to the caller, while
  global `admin` can see all inventories.
- `GET /cards/search`, `GET /cards/search/names`, and
  `GET /cards/oracle/{oracle_id}/printings` require a caller who can read at
  least one inventory, or a global `admin`.
- `GET /inventories/{inventory_slug}/items` and
  `GET /inventories/{inventory_slug}/audit` require inventory read access.
- `POST /inventories/{inventory_slug}/items`,
  `PATCH /inventories/{inventory_slug}/items/{item_id}`, and
  `DELETE /inventories/{inventory_slug}/items/{item_id}` require inventory
  write access.
- `POST /inventories` still requires a global `editor` or `admin`, and the
  creator is automatically granted `owner` membership on the new inventory.
- Existing inventories with no memberships are effectively admin-only until
  memberships are granted intentionally.
- In `shared_service`, caller-controlled `X-Actor-Id` values are not part of
  the trust boundary for audit attribution.
- In `shared_service`, `MTG_API_TRUST_ACTOR_HEADERS=true` is not a valid
  startup posture.
- In `shared_service`, blank or colliding verified-user header names are
  rejected at startup.
- The current deployment guidance expects the reverse proxy to strip any
  client-supplied identity headers before injecting verified values.
- Snapshot backup and restore are part of the supported recovery model for the
  current shared-service SQLite posture.
- `X-Request-Id` remains a supported tracing header and is echoed back in API
  responses.
- The API logs startup mode and unexpected failures. The main remaining
  blockers before broader shared deployment are rollout validation against the
  real membership model and clearer admin-only surface policy.

## Notes For Web V1

- The CLI still catches these errors as `ValueError` subclasses, so command-line
  behavior stays stable while the API gains a more explicit contract.
- This contract is intentionally small. More specific error codes can be added
  later, but the baseline envelope and status mapping should stay stable.
