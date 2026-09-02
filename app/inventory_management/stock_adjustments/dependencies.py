"""Stock adjustment slice dependencies."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies.auth import CurrentUserDependency
from app.db.session import get_db
from app.inventory_management.stock_adjustments.service import StockAdjustmentService


def get_stock_adjustment_service(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: CurrentUserDependency,
) -> StockAdjustmentService:
    return StockAdjustmentService(session, actor_permissions=current_user.permissions)


StockAdjustmentServiceDependency = Annotated[
    StockAdjustmentService, Depends(get_stock_adjustment_service)
]
