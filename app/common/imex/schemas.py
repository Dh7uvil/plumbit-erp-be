"""Import/export request and preview schemas."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ImexField(BaseModel):
    name: str
    label: str
    required: bool = False
    aliases: list[str] = Field(default_factory=list)
    group: str = "header"


class ImexColumn(BaseModel):
    index: int
    header: str


class ImexMappingEntry(BaseModel):
    column: str
    field: str


class ImportPreviewResponse(BaseModel):
    columns: list[ImexColumn] = Field(default_factory=list)
    suggested_mapping: list[ImexMappingEntry] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0


class ImportRequest(BaseModel):
    mapping: list[ImexMappingEntry] = Field(default_factory=list)


class ImportRowError(BaseModel):
    row_number: int
    message: str


class ImportResult(BaseModel):
    created_ids: list[UUID] = Field(default_factory=list)
    errors: list[ImportRowError] = Field(default_factory=list)
    created_count: int = 0
    error_count: int = 0
