"""Task request and response schemas."""

from datetime import datetime
from typing import ClassVar, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.schemas.filters import BaseFilter
from app.common.utils.datetime import ensure_utc
from app.common.utils.validators import normalize_required_text
from app.core.enums import TaskPriority, TaskRelatedEntityType, TaskStatus, TaskType


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part for part in value.split(",") if part.strip()]


class TaskFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {
            "created_at",
            "updated_at",
            "due_at",
            "title",
            "status",
            "priority",
            "sort_order",
            "task_number",
        }
    )
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    assignee_id: UUID | None = None
    mine: bool | None = None
    overdue: bool | None = None
    due_from: datetime | None = None
    due_to: datetime | None = None
    label_id: UUID | None = None
    related_entity_type: TaskRelatedEntityType | None = None
    related_entity_id: UUID | None = None
    statuses: str | None = None
    priorities: str | None = None
    assignee_ids: str | None = None
    label_ids: str | None = None
    task_types: str | None = None
    unassigned: bool | None = None
    parent_id: UUID | None = None
    top_level_only: bool | None = None

    def parsed_statuses(self) -> list[TaskStatus]:
        return [TaskStatus(value) for value in _split_csv(self.statuses)]

    def parsed_priorities(self) -> list[TaskPriority]:
        return [TaskPriority(value) for value in _split_csv(self.priorities)]

    def parsed_assignee_ids(self) -> list[UUID]:
        return [UUID(value) for value in _split_csv(self.assignee_ids)]

    def parsed_label_ids(self) -> list[UUID]:
        return [UUID(value) for value in _split_csv(self.label_ids)]

    def parsed_task_types(self) -> list[TaskType]:
        return [TaskType(value) for value in _split_csv(self.task_types)]

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


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_type: TaskType = TaskType.TASK
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: datetime | None = None
    assignee_id: UUID | None = None
    parent_id: UUID | None = None
    related_entity_type: TaskRelatedEntityType | None = None
    related_entity_id: UUID | None = None
    label_ids: list[UUID] = Field(default_factory=list)
    watcher_ids: list[UUID] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return normalize_required_text(value, field_name="title")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("due_at")
    @classmethod
    def normalize_due_at(cls, value: datetime | None) -> datetime | None:
        return _ensure_optional_utc(value)

    @model_validator(mode="after")
    def related_pair(self) -> Self:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError("related_entity_type and related_entity_id must be provided together")
        return self


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_type: TaskType | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None
    assignee_id: UUID | None = None
    parent_id: UUID | None = None
    related_entity_type: TaskRelatedEntityType | None = None
    related_entity_id: UUID | None = None
    status: TaskStatus | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="title")

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("due_at")
    @classmethod
    def normalize_due_at(cls, value: datetime | None) -> datetime | None:
        return _ensure_optional_utc(value)

    @model_validator(mode="after")
    def related_pair_and_no_status(self) -> Self:
        if (self.related_entity_type is None) != (self.related_entity_id is None):
            raise ValueError("related_entity_type and related_entity_id must be provided together")
        if self.status is not None:
            raise ValueError("status cannot be changed via PATCH; use POST /tasks/{id}/move")
        return self


class TaskMove(BaseModel):
    status: TaskStatus
    sort_order: int = Field(ge=0)


class TaskAssign(BaseModel):
    assignee_id: UUID | None = None


class TaskBulkAssignItem(BaseModel):
    task_id: UUID
    assignee_id: UUID | None = None


class TaskBulkAssign(BaseModel):
    items: list[TaskBulkAssignItem] = Field(min_length=1)


class TaskBulkStatusItem(BaseModel):
    task_id: UUID
    status: TaskStatus
    sort_order: int | None = Field(default=None, ge=0)


class TaskBulkStatus(BaseModel):
    items: list[TaskBulkStatusItem] = Field(min_length=1)


class TaskLabelSet(BaseModel):
    label_ids: list[UUID] = Field(default_factory=list)


class TaskWatcherSet(BaseModel):
    watcher_ids: list[UUID] = Field(default_factory=list)


class TaskChecklistItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    sort_order: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return normalize_required_text(value, field_name="title")


class TaskChecklistItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    is_done: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_required_text(value, field_name="title")


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        return normalize_required_text(value, field_name="body")


class TaskCommentUpdate(BaseModel):
    body: str = Field(min_length=1)

    @field_validator("body")
    @classmethod
    def normalize_body(cls, value: str) -> str:
        return normalize_required_text(value, field_name="body")


class TaskChecklistItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    task_id: UUID
    title: str
    is_done: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class TaskCommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    task_id: UUID
    body: str
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class TaskLabelSummary(BaseModel):
    id: UUID
    name: str
    color: str


class TaskParentSummary(BaseModel):
    id: UUID
    task_number: str
    title: str
    task_type: TaskType


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    task_number: str
    task_type: TaskType
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    assignee_id: UUID | None
    parent_id: UUID | None
    sort_order: int
    related_entity_type: TaskRelatedEntityType | None
    related_entity_id: UUID | None
    parent: TaskParentSummary | None = None
    subtask_count: int = 0
    subtask_done_count: int = 0
    labels: list[TaskLabelSummary] = Field(default_factory=list)
    watcher_ids: list[UUID] = Field(default_factory=list)
    checklist_items: list[TaskChecklistItemResponse] = Field(default_factory=list)
    available_actions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: UUID | None = None
    updated_by: UUID | None = None


class TaskBulkResultItem(BaseModel):
    task_id: UUID
    success: bool
    error: str | None = None
    data: TaskResponse | None = None


class TaskBulkResult(BaseModel):
    items: list[TaskBulkResultItem] = Field(default_factory=list)
    success_count: int = 0
    error_count: int = 0
