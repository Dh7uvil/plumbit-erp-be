"""History slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.history.service import HistoryService


def get_history_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> HistoryService:
    return HistoryService(session, actor_permissions=current_user.permissions)


HistoryServiceDependency = Annotated[HistoryService, Depends(get_history_service)]
