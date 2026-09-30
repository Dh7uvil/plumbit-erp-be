"""Year-end closing dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.erp.accounting.year_end.service import YearEndService


def get_year_end_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> YearEndService:
    return YearEndService(session, actor_permissions=current_user.permissions)


YearEndServiceDependency = Annotated[YearEndService, Depends(get_year_end_service)]
