"""Safe, stable application exceptions for API responses."""

from collections.abc import Mapping
from enum import StrEnum
from http import HTTPStatus


class ErrorCode(StrEnum):
    """Stable machine-readable application error codes."""

    AUTH_INVALID_CREDENTIALS = "AUTH_INVALID_CREDENTIALS"
    AUTH_TOKEN_EXPIRED = "AUTH_TOKEN_EXPIRED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TENANT_ACCESS_DENIED = "TENANT_ACCESS_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"
    FINANCIAL_TRANSACTION_LOCKED = "FINANCIAL_TRANSACTION_LOCKED"
    INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
    INTEGRATION_ERROR = "INTEGRATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Base exception containing only client-safe error information."""

    default_code = ErrorCode.INTERNAL_ERROR
    default_status = HTTPStatus.INTERNAL_SERVER_ERROR
    default_message = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = self.default_code
        self.status_code = int(self.default_status)
        self.message = message or self.default_message
        self.details = dict(details or {})
        super().__init__(self.message)


class InvalidCredentialsError(AppError):
    default_code = ErrorCode.AUTH_INVALID_CREDENTIALS
    default_status = HTTPStatus.UNAUTHORIZED
    default_message = "Invalid credentials"


class InvalidTokenError(InvalidCredentialsError):
    default_message = "Invalid authentication token"


class TokenTypeError(InvalidCredentialsError):
    default_message = "Unexpected authentication token type"


class TokenExpiredError(AppError):
    default_code = ErrorCode.AUTH_TOKEN_EXPIRED
    default_status = HTTPStatus.UNAUTHORIZED
    default_message = "Authentication token has expired"


class PermissionDeniedError(AppError):
    default_code = ErrorCode.PERMISSION_DENIED
    default_status = HTTPStatus.FORBIDDEN
    default_message = "Permission denied"


class TenantAccessDeniedError(AppError):
    default_code = ErrorCode.TENANT_ACCESS_DENIED
    default_status = HTTPStatus.FORBIDDEN
    default_message = "Tenant access denied"


class ResourceNotFoundError(AppError):
    default_code = ErrorCode.RESOURCE_NOT_FOUND
    default_status = HTTPStatus.NOT_FOUND
    default_message = "Resource not found"


class ValidationError(AppError):
    default_code = ErrorCode.VALIDATION_ERROR
    default_status = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "Request validation failed"


class DuplicateResourceError(AppError):
    default_code = ErrorCode.DUPLICATE_RESOURCE
    default_status = HTTPStatus.CONFLICT
    default_message = "Resource already exists"


class InvalidStatusTransitionError(AppError):
    default_code = ErrorCode.INVALID_STATUS_TRANSITION
    default_status = HTTPStatus.CONFLICT
    default_message = "Invalid status transition"


class FinancialTransactionLockedError(AppError):
    default_code = ErrorCode.FINANCIAL_TRANSACTION_LOCKED
    default_status = HTTPStatus.CONFLICT
    default_message = "Financial transaction is locked"


class InsufficientStockError(AppError):
    default_code = ErrorCode.INSUFFICIENT_STOCK
    default_status = HTTPStatus.CONFLICT
    default_message = "Insufficient stock available"


class IntegrationError(AppError):
    default_code = ErrorCode.INTEGRATION_ERROR
    default_status = HTTPStatus.BAD_GATEWAY
    default_message = "External integration failed"


class InternalError(AppError):
    """Explicit safe internal error; never pass an exception message into this class."""
