"""Conversation dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.conversations.service import ConversationService
from app.db.session import get_db


def get_conversation_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationService:
    return ConversationService(session)


ConversationServiceDependency = Annotated[
    ConversationService, Depends(get_conversation_service)
]
