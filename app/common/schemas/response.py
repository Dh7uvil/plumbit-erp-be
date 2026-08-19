"""Shared API response envelopes."""

from typing import Literal

from pydantic import BaseModel, Field


class ApiResponse[DataT](BaseModel):
    """Successful API response envelope."""

    success: Literal[True] = True
    data: DataT
    message: str | None = None
    meta: dict[str, object] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    """Safe, stable error information returned to a client."""

    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Failed API response envelope."""

    success: Literal[False] = False
    error: ErrorDetail
