"""Activity slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.crm.activities.service import ActivityService
from app.db.session import get_db


def get_activity_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> ActivityService:
    return ActivityService(session, actor_permissions=current_user.permissions)


ActivityServiceDependency = Annotated[ActivityService, Depends(get_activity_service)]
