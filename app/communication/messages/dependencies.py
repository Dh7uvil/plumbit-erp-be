"""Message dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.messages.service import MessageService
from app.db.session import get_db


def get_message_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> MessageService:
    return MessageService(session)


MessageServiceDependency = Annotated[MessageService, Depends(get_message_service)]
