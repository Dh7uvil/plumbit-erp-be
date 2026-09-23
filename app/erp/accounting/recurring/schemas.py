"""Recurring template schemas."""

from datetime import date, datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import RecurringDocumentKind, RecurringFrequency, RecurringTemplateStatus


class RecurringTemplateFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "next_run_date", "status"}
    )
    status: RecurringTemplateStatus | None = None
    document_kind: RecurringDocumentKind | None = None


class RecurringTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    document_kind: RecurringDocumentKind
    frequency: RecurringFrequency
    interval: int = Field(default=1, ge=1, le=36)
    next_run_date: date
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1, le=1000)
    template_payload: dict[str, Any]
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class RecurringTemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    frequency: RecurringFrequency | None = None
    interval: int | None = Field(default=None, ge=1, le=36)
    next_run_date: date | None = None
    end_date: date | None = None
    max_occurrences: int | None = Field(default=None, ge=1, le=1000)
    status: RecurringTemplateStatus | None = None
    template_payload: dict[str, Any] | None = None
    notes: str | None = None
    version: int | None = Field(default=None, ge=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class RecurringGenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_date: date
    document_kind: RecurringDocumentKind
    document_id: UUID | None
    document_number: str | None
    created_at: datetime


class RecurringTemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    document_kind: RecurringDocumentKind
    frequency: RecurringFrequency
    interval: int
    next_run_date: date
    end_date: date | None
    max_occurrences: int | None
    occurrences_generated: int
    status: RecurringTemplateStatus
    version: int
    template_payload: dict[str, Any]
    last_document_id: UUID | None
    last_document_number: str | None
    last_run_at: datetime | None
    notes: str | None
    generations: list[RecurringGenerationResponse] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
