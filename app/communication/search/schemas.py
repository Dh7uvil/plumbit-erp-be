"""Communication search schemas."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class SearchType(StrEnum):
    MESSAGES = "messages"
    PEOPLE = "people"
    GROUPS = "groups"
    FILES = "files"
    CONVERSATIONS = "conversations"


class SearchResultItem(BaseModel):
    type: SearchType
    id: UUID
    title: str
    subtitle: str | None = None
    conversation_id: UUID | None = None
    seq: int | None = None
    highlight: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResultItem] = Field(default_factory=list)


class ConversationMessageSearchParams(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=50, ge=1, le=100)
