"""Chat attachment dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.attachments.service import ChatAttachmentService
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.storage.client import S3Storage, get_storage


def get_chat_attachment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChatAttachmentService:
    return ChatAttachmentService(session, storage, settings)


ChatAttachmentServiceDependency = Annotated[
    ChatAttachmentService, Depends(get_chat_attachment_service)
]
