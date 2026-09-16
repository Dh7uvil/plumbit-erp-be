"""Activity feed request and response schemas."""

from datetime import datetime
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.common.schemas.filters import BaseFilter

ActivityKind = Literal["approval", "edit", "attachment"]


class ActivityFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset({"created_at"})

    entity_type: str = Field(min_length=1, max_length=100)
    entity_id: UUID


class ActivityChangedField(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None


class ActivityEntry(BaseModel):
    action: str
    actor_id: UUID | None
    actor_name: str | None
    actor_email: str | None
    occurred_at: datetime
    changed_fields: list[ActivityChangedField]
    status: str
    kind: ActivityKind
    summary: str | None = None
