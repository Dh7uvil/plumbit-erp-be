"""Presence schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import PresenceStatus


class PresenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    status: PresenceStatus
    custom_status: str | None
    last_seen_at: datetime | None
    last_heartbeat_at: datetime | None


class HeartbeatRequest(BaseModel):
    status: PresenceStatus = PresenceStatus.ONLINE
    custom_status: str | None = Field(default=None, max_length=100)
