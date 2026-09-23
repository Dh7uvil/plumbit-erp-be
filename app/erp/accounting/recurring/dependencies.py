"""Recurring slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.recurring.service import RecurringService


def get_recurring_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> RecurringService:
    return RecurringService(session, actor_permissions=current_user.permissions)


RecurringServiceDependency = Annotated[RecurringService, Depends(get_recurring_service)]
