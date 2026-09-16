"""Slice-level FastAPI dependencies for notification preferences."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notification_preferences.service import NotificationPreferenceService
from app.db.session import get_db


def get_notification_preference_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationPreferenceService:
    return NotificationPreferenceService(session)


NotificationPreferenceServiceDependency = Annotated[
    NotificationPreferenceService, Depends(get_notification_preference_service)
]
