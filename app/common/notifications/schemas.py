"""Notification API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event: str
    entity_type: str
    entity_id: UUID | None
    title: str
    body: str
    read_at: datetime | None
    created_at: datetime


class UnreadCountResponse(BaseModel):
    count: int
