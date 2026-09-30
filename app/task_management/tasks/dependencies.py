"""Task FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.task_management.tasks.service import TaskService


def get_task_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> TaskService:
    return TaskService(
        session,
        actor_permissions=current_user.permissions,
        actor=current_user.actor,
    )


TaskServiceDependency = Annotated[TaskService, Depends(get_task_service)]
