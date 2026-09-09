"""Activity slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.activity.service import ActivityService
from app.db.session import get_db


def get_activity_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ActivityService:
    return ActivityService(session)


ActivityServiceDependency = Annotated[ActivityService, Depends(get_activity_service)]
