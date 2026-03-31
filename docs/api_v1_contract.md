# API V1 Contract

This document defines the JSON and error-shaping rules the web layer should
preserve for the first API-backed version of the project.

## Response Shaping

- Service responses are serialized through
  `mtg_source_stack.inventory.response_models.serialize_response`.
- Money values are emitted as decimal strings, not JSON numbers.
  Example: `"2.50"`, not `2.5`.
- Absent optional values are emitted as `null`.
- Lists stay lists, including fields like catalog `finishes` and inventory
  `tags`.
- Dates remain ISO-8601 strings.

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

## Notes For Web V1

- The CLI still catches these errors as `ValueError` subclasses, so command-line
  behavior stays stable while the API gains a more explicit contract.
- This contract is intentionally small. More specific error codes can be added
  later, but the baseline envelope and status mapping should stay stable.
