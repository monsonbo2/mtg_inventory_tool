# API V1 Contract

This document defines the JSON and error-shaping rules the web layer should
preserve for the first API-backed version of the project.

## Response Shaping

- Service responses are serialized through
  `mtg_source_stack.inventory.response_models.serialize_response`.
- The FastAPI layer publishes explicit HTTP response models in OpenAPI rather
  than relying on inferred `Any` responses.
- Money values are emitted as decimal strings, not JSON numbers.
  Example: `"2.50"`, not `2.5`.
- Absent optional values are emitted as `null`.
- Lists stay lists, including fields like catalog `finishes` and inventory
  `tags`.
- Dates remain ISO-8601 strings.
- `PATCH /inventories/{inventory_slug}/items/{item_id}` returns
  operation-specific result shapes rather than one generic mutation envelope.
- Audit event `before`, `after`, and `metadata` fields remain intentionally
  loose JSON objects in web-v1.
- `GET /health` returns mode-oriented fields such as `status`,
  `auto_migrate`, and `trusted_actor_headers`; it does not expose the SQLite
  filesystem path in web-v1.

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

- `ValidationError` -> `400`
- `NotFoundError` -> `404`
- `ConflictError` -> `409`
- `SchemaNotReadyError` -> `503`
- unexpected exceptions -> `500` with code `internal_error`

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
- Transport/runtime concurrency guarantees are not yet part of this contract.
- The current API shell is intended for trusted local/demo usage and currently
  wraps synchronous inventory and SQLite-backed services.
- By default, the API ignores caller-supplied `X-Actor-Id` values and records
  mutating audit entries with `actor_type="api"` and `actor_id="local-demo"`.
- For explicit local/dev testing, setting
  `MTG_API_TRUST_ACTOR_HEADERS=true` allows non-empty `X-Actor-Id` header
  values to flow into audit attribution.
- `X-Request-Id` remains a supported tracing header and is echoed back in API
  responses.
- The demo API logs startup mode and unexpected failures, but it still needs a
  dedicated execution-boundary / concurrency-hardening pass before broader
  deployment.

## Notes For Web V1

- The CLI still catches these errors as `ValueError` subclasses, so command-line
  behavior stays stable while the API gains a more explicit contract.
- This contract is intentionally small. More specific error codes can be added
  later, but the baseline envelope and status mapping should stay stable.
