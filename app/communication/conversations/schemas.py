"""Conversation schemas."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.schemas.filters import BaseFilter
from app.core.enums import ConversationKind, ParticipantRole


class ConversationFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "last_message_at", "name", "kind"}
    )
    kind: ConversationKind | None = None


class LastMessagePreview(BaseModel):
    id: UUID
    sender_id: UUID | None
    body: str | None
    kind: str
    created_at: datetime


class ParticipantResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    role: ParticipantRole
    joined_at: datetime
    last_read_seq: int = 0
    is_muted: bool
    is_pinned: bool


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ConversationKind
    name: str | None
    description: str | None
    channel_name: str
    message_seq: int
    last_message_at: datetime | None
    last_message: LastMessagePreview | None = None
    only_admins_can_post: bool
    is_locked: bool
    unread_count: int = 0
    participants: list[ParticipantResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ConversationCreate(BaseModel):
    kind: ConversationKind
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    participant_user_ids: list[UUID] = Field(default_factory=list)
    other_user_id: UUID | None = None


class ConversationForContextCreate(BaseModel):
    context_entity_type: str = Field(min_length=1, max_length=50)
    context_entity_id: UUID
    participant_user_ids: list[UUID] = Field(default_factory=list)
    name: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    only_admins_can_post: bool | None = None
    is_locked: bool | None = None


class ParticipantAdd(BaseModel):
    user_id: UUID
    role: ParticipantRole = ParticipantRole.MEMBER


class ParticipantRoleUpdate(BaseModel):
    role: ParticipantRole


class MySettingsUpdate(BaseModel):
    is_muted: bool | None = None
    is_pinned: bool | None = None
    notification_level: str | None = None


class ReadMarker(BaseModel):
    up_to_seq: int = Field(ge=0)


class TypingEvent(BaseModel):
    is_typing: bool = True


class UnreadSummaryResponse(BaseModel):
    total_unread: int
    conversations: list[dict[str, object]] = Field(default_factory=list)
