"""Chat attachment schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ChatAttachmentKind


class AttachmentPresignRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=150)
    kind: ChatAttachmentKind
    conversation_id: UUID


class AttachmentPresignResponse(BaseModel):
    attachment_id: UUID
    upload_url: str
    storage_key: str
    max_size_bytes: int


class AttachmentCompleteRequest(BaseModel):
    conversation_id: UUID
    client_message_id: str | None = Field(default=None, max_length=64)
    duration_ms: int | None = Field(default=None, ge=0)
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)


class AttachmentDownloadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attachment_id: UUID
    download_url: str
    content_type: str
    size_bytes: int
    original_filename: str
