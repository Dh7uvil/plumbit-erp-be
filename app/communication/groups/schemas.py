"""Group conversation schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.communication.conversations.schemas import ConversationResponse, ParticipantResponse
from app.core.enums import ConversationKind


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    member_user_ids: list[UUID] = Field(default_factory=list)
    max_members: int | None = Field(default=None, ge=2)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = None
    image_attachment_id: UUID | None = None


class GroupMembersAdd(BaseModel):
    user_ids: list[UUID] = Field(min_length=1)


class GroupResponse(ConversationResponse):
    max_members: int
    only_admins_can_edit_info: bool
    image_attachment_id: UUID | None = None
    context_entity_type: str | None = None
    context_entity_id: UUID | None = None

    @classmethod
    def from_conversation(
        cls,
        conv: ConversationResponse,
        *,
        max_members: int,
        only_admins_can_edit_info: bool,
        image_attachment_id: UUID | None,
        context_entity_type: str | None,
        context_entity_id: UUID | None,
    ) -> "GroupResponse":
        return cls(
            **conv.model_dump(),
            max_members=max_members,
            only_admins_can_edit_info=only_admins_can_edit_info,
            image_attachment_id=image_attachment_id,
            context_entity_type=context_entity_type,
            context_entity_id=context_entity_id,
        )


class GroupMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    role: str
    joined_at: datetime


__all__ = [
    "ConversationKind",
    "GroupCreate",
    "GroupMembersAdd",
    "GroupMemberResponse",
    "GroupResponse",
    "GroupUpdate",
    "ParticipantResponse",
]
