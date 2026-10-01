"""Chat notification settings dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.settings.service import ChatNotificationSettingsService
from app.db.session import get_db


def get_chat_notification_settings_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ChatNotificationSettingsService:
    return ChatNotificationSettingsService(session)


ChatNotificationSettingsServiceDependency = Annotated[
    ChatNotificationSettingsService, Depends(get_chat_notification_settings_service)
]
