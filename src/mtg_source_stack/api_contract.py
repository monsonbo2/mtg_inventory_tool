"""Framework-agnostic helpers for the public JSON/error contract."""

from __future__ import annotations

from typing import Any

from .errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    MtgStackError,
    NotFoundError,
    SchemaNotReadyError,
    ValidationError,
)


def api_error_status(exc: Exception) -> int:
    if isinstance(exc, SchemaNotReadyError):
        return 503
    if isinstance(exc, AuthenticationError):
        return 401
    if isinstance(exc, AuthorizationError):
        return 403
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, ConflictError):
        return 409
    if isinstance(exc, ValidationError):
        return 400
    return 500


def api_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, MtgStackError):
        error_payload: dict[str, Any] = {
            "code": exc.error_code,
            "message": str(exc),
        }
        if exc.details is not None:
            error_payload["details"] = exc.details
        return {"error": error_payload}
    return {
        "error": {
            "code": "internal_error",
            "message": "Internal server error.",
        }
    }
