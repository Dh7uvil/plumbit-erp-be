"""Presence dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.presence.service import PresenceService
from app.db.session import get_db


def get_presence_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PresenceService:
    return PresenceService(session)


PresenceServiceDependency = Annotated[PresenceService, Depends(get_presence_service)]
