"""Task label FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.task_management.task_labels.service import TaskLabelService


def get_task_label_service(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TaskLabelService:
    return TaskLabelService(session)


TaskLabelServiceDependency = Annotated[TaskLabelService, Depends(get_task_label_service)]
