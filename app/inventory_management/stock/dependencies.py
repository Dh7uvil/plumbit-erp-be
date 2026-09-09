"""Stock inquiry slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.stock.service import StockService


def get_stock_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> StockService:
    return StockService(session, actor_permissions=current_user.permissions)


StockServiceDependency = Annotated[StockService, Depends(get_stock_service)]
