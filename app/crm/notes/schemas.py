"""Note request and response schemas."""

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import CrmRelatedEntityType


class NoteFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at", "updated_at"})
    related_entity_type: CrmRelatedEntityType | None = None
    related_entity_id: UUID | None = None

    @model_validator(mode="after")
    def related_pair(self) -> Self:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError("related_entity_type and related_entity_id must be provided together")
        return self


class NoteCreate(BaseModel):
    body: str = Field(min_length=1)
    related_entity_type: CrmRelatedEntityType
    related_entity_id: UUID

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        return normalize_required_text(value, field_name="body")


class NoteUpdate(BaseModel):
    body: str | None = Field(default=None, min_length=1)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="body")


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    body: str
    related_entity_type: CrmRelatedEntityType
    related_entity_id: UUID
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
