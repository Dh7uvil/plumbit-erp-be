"""Message schemas."""

from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import MessageKind


class MessageAttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    thumbnail_url: str | None = None


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    conversation_id: UUID
    seq: int
    sender_id: UUID | None
    kind: MessageKind
    body: str | None
    reply_to_message_id: UUID | None
    client_message_id: str | None
    edited_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    attachment: MessageAttachmentResponse | None = None
    system_payload: dict | None = None


class MessageCreate(BaseModel):
    body: str = Field(min_length=1)
    kind: Literal[MessageKind.TEXT] = MessageKind.TEXT
    reply_to_message_id: UUID | None = None
    client_message_id: str | None = Field(default=None, max_length=64)


class MessageUpdate(BaseModel):
    body: str = Field(min_length=1)


class MessageListParams(BaseModel):
    before_seq: int | None = Field(default=None, ge=1)
    after_seq: int | None = Field(default=None, ge=0)
    limit: int = Field(default=50, ge=1, le=200)


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    has_more: bool


class DeliveredMarker(BaseModel):
    up_to_seq: int = Field(ge=0)


class MessageForwardRequest(BaseModel):
    conversation_id: UUID
    client_message_id: str | None = Field(default=None, max_length=64)


class ReactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: UUID
    user_id: UUID
    emoji: str


class SavedMessageResponse(BaseModel):
    message: MessageResponse
    saved_at: datetime
