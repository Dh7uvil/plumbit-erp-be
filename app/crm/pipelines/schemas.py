"""Pipeline and stage request/response schemas."""

from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.validators import normalize_required_text
from app.core.enums import PipelineStageKind


class PipelineFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "name", "is_default", "is_active"}
    )
    is_active: bool | None = None
    is_default: bool | None = None


class PipelineStageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    sort_order: int = Field(ge=0, le=999)
    probability: Decimal = Field(ge=0, le=100)
    stage_kind: PipelineStageKind

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class PipelineStageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    sort_order: int | None = Field(default=None, ge=0, le=999)
    probability: Decimal | None = Field(default=None, ge=0, le=100)
    stage_kind: PipelineStageKind | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class PipelineStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    pipeline_id: UUID
    name: str
    sort_order: int
    probability: Decimal
    stage_kind: PipelineStageKind
    created_at: datetime
    updated_at: datetime


class PipelineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    is_default: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return normalize_required_text(value, field_name="name")


class PipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="name")


class PipelineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
    stages: list[PipelineStageResponse] = Field(default_factory=list)


class PipelineListItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    name: str
    is_default: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
