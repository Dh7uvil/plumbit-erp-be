"""Central registration of safe API error responses."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from http import HTTPStatus
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.core.exceptions import AppError, ErrorCode

logger = logging.getLogger(__name__)

type ExceptionHandler = Callable[
    [Request, Exception],
    Response | Awaitable[Response],
]


def _error_response(
    *,
    status_code: int,
    code: ErrorCode | str,
    message: str,
    details: object | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "success": False,
            "error": {
                "code": str(code),
                "message": message,
                "details": details if details is not None else {},
            },
        },
    )


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    errors: list[dict[str, object]] = []
    field_errors: dict[str, str] = {}
    for error in exc.errors():
        location = [
            item if isinstance(item, (str, int)) else str(item) for item in error.get("loc", ())
        ]
        message = str(error.get("msg", "Invalid value"))
        errors.append(
            {
                "loc": location,
                "location": location,
                "msg": message,
                "message": message,
                "type": str(error.get("type", "validation_error")),
            }
        )
        field_name = ".".join(str(part) for part in location if part != "body")
        if field_name:
            field_errors[field_name] = message
    logger.info(
        "request_validation_failed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "errors": errors,
        },
    )
    return _error_response(
        status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        code=ErrorCode.VALIDATION_ERROR,
        message="Request validation failed",
        details={"errors": errors, **field_errors},
    )


def _http_error_code(status_code: int) -> ErrorCode | str:
    status_codes: dict[int, ErrorCode] = {
        HTTPStatus.BAD_REQUEST: ErrorCode.VALIDATION_ERROR,
        HTTPStatus.UNAUTHORIZED: ErrorCode.AUTH_INVALID_CREDENTIALS,
        HTTPStatus.FORBIDDEN: ErrorCode.PERMISSION_DENIED,
        HTTPStatus.NOT_FOUND: ErrorCode.RESOURCE_NOT_FOUND,
    }
    return status_codes.get(status_code, "HTTP_ERROR")


def _safe_http_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Request failed"


async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    return _error_response(
        status_code=exc.status_code,
        code=_http_error_code(exc.status_code),
        message=_safe_http_message(exc.status_code),
        headers=exc.headers,
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "unhandled_request_exception",
        extra={
            "method": request.method,
            "path": request.url.path,
            "exception_type": type(exc).__name__,
        },
    )
    return _error_response(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected error occurred",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register handlers in specific-to-general order."""

    app.add_exception_handler(AppError, cast(ExceptionHandler, app_error_handler))
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_error_handler),
    )
    app.add_exception_handler(
        StarletteHTTPException,
        cast(ExceptionHandler, http_exception_handler),
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
