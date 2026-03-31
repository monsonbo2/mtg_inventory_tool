"""Framework-agnostic helpers for the public JSON/error contract."""

from __future__ import annotations

from typing import Any

from .errors import ConflictError, MtgStackError, NotFoundError, SchemaNotReadyError, ValidationError


def api_error_status(exc: Exception) -> int:
    if isinstance(exc, SchemaNotReadyError):
        return 503
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ConflictError):
        return 409
    if isinstance(exc, ValidationError):
        return 400
    return 500


def api_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, MtgStackError):
        return {
            "error": {
                "code": exc.error_code,
                "message": str(exc),
            }
        }
    return {
        "error": {
            "code": "internal_error",
            "message": "Internal server error.",
        }
    }
