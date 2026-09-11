"""Shared warning payloads for successful writes that still need attention."""

from typing import Any

from pydantic import BaseModel, Field


class DocumentWarning(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
