"""Sales return slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.sales_returns.service import SalesReturnService


def get_sales_return_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> SalesReturnService:
    return SalesReturnService(session, actor_permissions=current_user.permissions)


SalesReturnServiceDependency = Annotated[SalesReturnService, Depends(get_sales_return_service)]
