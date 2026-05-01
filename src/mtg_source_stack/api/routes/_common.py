from __future__ import annotations

from typing import Any

from ...inventory.response_models import serialize_response
from ..request_models import SEARCH_LANG_DESCRIPTION
from ..response_models import ApiErrorResponse

PRINTINGS_LANG_DESCRIPTION = (
    f"{SEARCH_LANG_DESCRIPTION} Omit this parameter to prefer English printings by default. "
    "Use `all` to include every available catalog language."
)
SEARCH_SCOPE_DESCRIPTION = (
    "Catalog scope to search. Omit this parameter or use `default` for the mainline card-add flow. "
    "Use `all` to include auxiliary catalog objects such as tokens, emblems, and art-series rows."
)

ERROR_RESPONSE_DESCRIPTIONS = {
    401: "Authentication required",
    403: "Forbidden",
    400: "Validation error",
    404: "Not found",
    409: "Conflict",
    500: "Internal server error",
    503: "Schema not ready",
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    return {
        status_code: {
            "model": ApiErrorResponse,
            "description": ERROR_RESPONSE_DESCRIPTIONS[status_code],
        }
        for status_code in status_codes
    }


def _serialize(payload: Any) -> Any:
    return serialize_response(payload)
