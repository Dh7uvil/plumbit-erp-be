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
    INVENTORY_INSUFFICIENT_STOCK = "INVENTORY_INSUFFICIENT_STOCK"
    INSUFFICIENT_STOCK = INVENTORY_INSUFFICIENT_STOCK
    PERIOD_LOCKED = "PERIOD_LOCKED"
    PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK = "PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK"
    DRAFT_DOCUMENT_NOT_POSTED = "DRAFT_DOCUMENT_NOT_POSTED"
    DOCUMENT_STALE = "DOCUMENT_STALE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    EXCHANGE_RATE_MISSING = "EXCHANGE_RATE_MISSING"
    EINVOICE_NOT_READY = "EINVOICE_NOT_READY"
    EINVOICE_REJECTED = "EINVOICE_REJECTED"
    EINVOICE_ASP_UNAVAILABLE = "EINVOICE_ASP_UNAVAILABLE"
    EINVOICE_ALREADY_EXCHANGED = "EINVOICE_ALREADY_EXCHANGED"
    INTEGRATION_ERROR = "INTEGRATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    RATE_LIMITED = "RATE_LIMITED"


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
    default_code = ErrorCode.INVENTORY_INSUFFICIENT_STOCK
    default_status = HTTPStatus.CONFLICT
    default_message = "Insufficient physical stock. Post the purchase invoice / GRN first."


InventoryInsufficientStockError = InsufficientStockError


class PeriodLockedError(AppError):
    default_code = ErrorCode.PERIOD_LOCKED
    default_status = HTTPStatus.CONFLICT
    default_message = "This date falls in a locked period"


class PeriodLockBlockedNegativeStockError(AppError):
    default_code = ErrorCode.PERIOD_LOCK_BLOCKED_NEGATIVE_STOCK
    default_status = HTTPStatus.CONFLICT
    default_message = "Period lock is blocked while a warehouse has negative on-hand stock"


class DraftDocumentNotPostedError(AppError):
    default_code = ErrorCode.DRAFT_DOCUMENT_NOT_POSTED
    default_status = HTTPStatus.CONFLICT
    default_message = "Draft documents cannot be posted as a side effect of save"


class DocumentStaleError(AppError):
    default_code = ErrorCode.DOCUMENT_STALE
    default_status = HTTPStatus.CONFLICT
    default_message = "This document was changed by another user. Reload and retry."


class IdempotencyConflictError(AppError):
    default_code = ErrorCode.IDEMPOTENCY_CONFLICT
    default_status = HTTPStatus.CONFLICT
    default_message = "Idempotency key was reused with a different request body"


class ExchangeRateMissingError(AppError):
    default_code = ErrorCode.EXCHANGE_RATE_MISSING
    default_status = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "No exchange rate for this currency on the document date"


class EinvoiceNotReadyError(AppError):
    default_code = ErrorCode.EINVOICE_NOT_READY
    default_status = HTTPStatus.UNPROCESSABLE_ENTITY
    default_message = "Document is not ready for e-invoice submission"


class EinvoiceRejectedError(AppError):
    default_code = ErrorCode.EINVOICE_REJECTED
    default_status = HTTPStatus.CONFLICT
    default_message = "E-invoice was rejected; post a credit note rather than editing"


class EinvoiceAspUnavailableError(AppError):
    default_code = ErrorCode.EINVOICE_ASP_UNAVAILABLE
    default_status = HTTPStatus.BAD_GATEWAY
    default_message = "E-invoicing service provider is unavailable"


class EinvoiceAlreadyExchangedError(AppError):
    default_code = ErrorCode.EINVOICE_ALREADY_EXCHANGED
    default_status = HTTPStatus.CONFLICT
    default_message = "E-invoice has already been exchanged"


class IntegrationError(AppError):
    default_code = ErrorCode.INTEGRATION_ERROR
    default_status = HTTPStatus.BAD_GATEWAY
    default_message = "External integration failed"


class RateLimitExceededError(AppError):
    default_code = ErrorCode.RATE_LIMITED
    default_status = HTTPStatus.TOO_MANY_REQUESTS
    default_message = "Too many authentication attempts"


class InternalError(AppError):
    """Explicit safe internal error; never pass an exception message into this class."""
