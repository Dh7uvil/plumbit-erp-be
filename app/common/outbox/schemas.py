"""Outbox admin request and response schemas."""

from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.schemas.filters import BaseFilter
from app.core.enums import OutboxStatus


class OutboxFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "available_at", "status", "event_type"}
    )

    status: OutboxStatus | None = None
    event_type: str | None = Field(default=None, max_length=80)
    aggregate_type: str | None = Field(default=None, max_length=50)
    aggregate_id: UUID | None = None


class OutboxEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    dedupe_key: str | None
    payload: dict[str, Any] | None
    status: OutboxStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    locked_at: datetime | None
    locked_by: str | None
    last_error: str | None
    processed_at: datetime | None
    request_id: str | None
    created_at: datetime
    updated_at: datetime
