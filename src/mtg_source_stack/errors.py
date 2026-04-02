"""Shared application errors for service and API layers."""

from __future__ import annotations


class MtgStackError(ValueError):
    """Base class for domain errors that should survive into API mapping."""

    default_error_code = "application_error"

    def __init__(self, message: str, *, error_code: str | None = None) -> None:
        super().__init__(message)
        self.error_code = error_code or self.default_error_code


class ValidationError(MtgStackError):
    default_error_code = "validation_error"


class AuthenticationError(MtgStackError):
    default_error_code = "authentication_required"


class AuthorizationError(MtgStackError):
    default_error_code = "forbidden"


class NotFoundError(MtgStackError):
    default_error_code = "not_found"


class ConflictError(MtgStackError):
    default_error_code = "conflict"


class SchemaNotReadyError(MtgStackError):
    default_error_code = "schema_not_ready"
