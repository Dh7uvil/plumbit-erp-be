"""Attachment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.attachments.service import AttachmentService
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.integrations.storage.client import S3Storage, get_storage


def get_attachment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[S3Storage, Depends(get_storage)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AttachmentService:
    return AttachmentService(session, storage, settings)


AttachmentServiceDependency = Annotated[AttachmentService, Depends(get_attachment_service)]
