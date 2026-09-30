"""AI assistant request and response schemas."""

from uuid import UUID

from pydantic import BaseModel, Field


class AiContextEntity(BaseModel):
    """Optional ERP record the user is asking about."""

    entity_type: str | None = Field(default=None, max_length=50)
    entity_id: UUID | None = None


class AiAssistRequest(BaseModel):
    """Prompt plus optional on-screen context."""

    prompt: str = Field(min_length=1, max_length=4000)
    context: AiContextEntity | None = None


class AiSuggestion(BaseModel):
    """Single read-only suggestion returned to the client."""

    title: str = Field(max_length=200)
    body: str = Field(max_length=8000)


class AiAssistResponse(BaseModel):
    """Structured, read-only assistant output."""

    suggestions: list[AiSuggestion]
    provider: str = Field(max_length=20)
    read_only: bool = True
    request_id: UUID
