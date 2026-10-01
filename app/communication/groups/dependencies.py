"""Group dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.communication.groups.service import GroupService
from app.db.session import get_db


def get_group_service(session: Annotated[AsyncSession, Depends(get_db)]) -> GroupService:
    return GroupService(session)


GroupServiceDependency = Annotated[GroupService, Depends(get_group_service)]
