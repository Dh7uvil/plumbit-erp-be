"""Call dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.calls.service import CallService
from app.db.session import get_db


def get_call_service(session: Annotated[AsyncSession, Depends(get_db)]) -> CallService:
    return CallService(session)


CallServiceDependency = Annotated[CallService, Depends(get_call_service)]
