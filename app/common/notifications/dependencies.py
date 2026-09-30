"""Slice-level FastAPI dependencies for notifications."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.notifications.service import NotificationService
from app.db.session import get_db


def get_notification_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> NotificationService:
    return NotificationService(session)


NotificationServiceDependency = Annotated[
    NotificationService, Depends(get_notification_service)
]
