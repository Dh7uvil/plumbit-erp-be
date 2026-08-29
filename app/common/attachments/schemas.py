"""Attachment request and response schemas."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.common.schemas.filters import BaseFilter
from app.core.enums import AttachmentEntityType


class AttachmentFilter(BaseFilter):
    allowed_sort_fields: ClassVar[frozenset[str]] = frozenset(
        {"created_at", "updated_at", "original_filename", "size_bytes"}
    )
    entity_type: AttachmentEntityType
    entity_id: UUID


class AttachmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    entity_type: AttachmentEntityType
    entity_id: UUID
    original_filename: str
    content_type: str
    size_bytes: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class AttachmentDetailResponse(AttachmentResponse):
    download_url: str = Field(description="Short-lived presigned GET URL")
