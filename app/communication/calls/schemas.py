"""Call schemas."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.schemas.filters import BaseFilter
from app.core.enums import CallKind, CallParticipantStatus, CallScope, CallStatus


class CallFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "started_at", "ended_at", "status"}
    )
    status: CallStatus | None = None
    conversation_id: UUID | None = None
    mine: bool = True


class CallParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    rtc_uid: int
    status: CallParticipantStatus
    is_audio_muted: bool
    is_video_enabled: bool
    is_screen_sharing: bool


class CallResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    channel_name: str
    kind: CallKind
    scope: CallScope
    status: CallStatus
    initiated_by: UUID | None
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None
    duration_seconds: int | None
    participants: list[CallParticipantResponse] = Field(default_factory=list)
    rtc_token: str | None = None
    rtc_uid: int | None = None
    token_expires_at: datetime | None = None


class CallCreate(BaseModel):
    conversation_id: UUID | None = None
    user_id: UUID | None = None
    kind: CallKind = CallKind.VIDEO

    @model_validator(mode="after")
    def validate_target(self) -> CallCreate:
        if self.conversation_id is None and self.user_id is None:
            raise ValueError("Either conversation_id or user_id is required")
        return self


class CallMediaUpdate(BaseModel):
    is_audio_muted: bool | None = None
    is_video_enabled: bool | None = None
    is_screen_sharing: bool | None = None
