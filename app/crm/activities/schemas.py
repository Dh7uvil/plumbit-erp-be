"""Activity request and response schemas."""

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.datetime import ensure_utc
from app.common.utils.validators import normalize_required_text
from app.core.enums import ActivityPriority, ActivityStatus, ActivityType, CrmRelatedEntityType


class ActivityFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "due_at",
            "start_at",
            "subject",
            "status",
            "priority",
            "activity_type",
        }
    )
    related_entity_type: CrmRelatedEntityType | None = None
    related_entity_id: UUID | None = None
    owner_id: UUID | None = None
    status: ActivityStatus | None = None
    activity_type: ActivityType | None = None
    overdue: bool | None = None
    mine: bool | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None

    @model_validator(mode="after")
    def related_pair_and_due_range(self) -> Self:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError("related_entity_type and related_entity_id must be provided together")
        if self.due_from is not None and self.due_to is not None and self.due_from > self.due_to:
            raise ValueError("due_from must be before or equal to due_to")
        return self


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _ensure_optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return ensure_utc(value)


class ActivityCreate(BaseModel):
    activity_type: ActivityType
    subject: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: ActivityPriority = ActivityPriority.MEDIUM
    due_at: datetime | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    owner_id: UUID | None = None
    related_entity_type: CrmRelatedEntityType
    related_entity_id: UUID

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str) -> str:
        return normalize_required_text(value, field_name="subject")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("due_at", "start_at", "end_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_optional_utc(value)

    @model_validator(mode="after")
    def validate_schedule(self) -> Self:
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class ActivityUpdate(BaseModel):
    activity_type: ActivityType | None = None
    subject: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: ActivityPriority | None = None
    due_at: datetime | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    owner_id: UUID | None = None
    related_entity_type: CrmRelatedEntityType | None = None
    related_entity_id: UUID | None = None
    status: ActivityStatus | None = None

    @field_validator("subject")
    @classmethod
    def normalize_subject(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="subject")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("due_at", "start_at", "end_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return _ensure_optional_utc(value)

    @model_validator(mode="after")
    def related_pair_and_schedule(self) -> Self:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError("related_entity_type and related_entity_id must be provided together")
        if self.start_at is not None and self.end_at is not None and self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.status is not None and self.status not in {
            ActivityStatus.OPEN,
            ActivityStatus.CANCELLED,
        }:
            raise ValueError("status can only be set to OPEN or CANCELLED via PATCH")
        return self


class ActivityComplete(BaseModel):
    outcome: str | None = None

    @field_validator("outcome")
    @classmethod
    def normalize_outcome(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    activity_type: ActivityType
    subject: str
    description: str | None
    status: ActivityStatus
    priority: ActivityPriority
    due_at: datetime | None
    start_at: datetime | None
    end_at: datetime | None
    duration_minutes: int | None
    outcome: str | None
    owner_id: UUID | None
    related_entity_type: CrmRelatedEntityType
    related_entity_id: UUID
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None
